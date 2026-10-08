"""FDAI proof harness for Java and C#: run inside the disposable code-build-prove sandbox only.

Standard library only. Java and C# cannot replace a loaded module, so the harness rewrites a copy
of each fix-site file without changing any line number. Every argument of a known sink call, and
every value assigned to a known sink property, passes through a recording hook first. The hook
records the value and always returns an inert value of the same type (a path that cannot exist),
so a sink that still runs afterwards cannot reach a real program, file, or query. The harness
then compiles the copy alone with the supplied toolchain (javac beside ``java``, or the SDK's
Roslyn compiler under ``dotnet``), calls every method and constructor it declares with the
marker in each caller-controlled input, and reports a target ``proven`` only when the marker
reaches a hooked sink of the target's class, in the shape the class predicate requires, from a
stack frame at the fix-site file and line. A file that needs project dependencies does not
compile alone and stays unproven with ``compile_failed``.

This file is a catalog asset, not an FDAI module: the proof lane copies it into the sandbox.

Usage: python3 -I fdai_prove_managed.py SOURCE_ROOT TARGETS_JSON TOOLCHAIN
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = "FDAICANARYXY"
INERT = "/nonexistent/fdai-inert"
VALUES = {
    "command_injection": "x;" + MARKER,
    "sql_injection": "x'" + MARKER,
    "path_traversal": "../../" + MARKER,
}
COMPILE_SECONDS = 120
RUN_SECONDS = 30
OUTPUT_BYTES = 65_536

# (pattern, sink name, class, mode). Only the argument that carries the class is matched: the
# first argument of a call ("first"), the value of an assignment ("assign"), or, for a command,
# the argument vector built from its program and arguments in call order. Only a single
# command-line string ("line" for Runtime.exec(String), "arguments" for a .NET argument string) is
# split into words; every other element stays whole. Every other argument of a hooked call is
# still made inert but never counts, so file contents, bound query parameters, and environment
# entries cannot prove a finding.
_JAVA_SINKS = [
    (r"\.exec\s*\(", "Runtime.exec", "command_injection", "line"),
    (r"\bnew\s+ProcessBuilder\s*\(", "ProcessBuilder", "command_injection", "command"),
    (r"\.command\s*\(", "ProcessBuilder.command", "command_injection", "command"),
    (
        r"\.(?:executeQuery|executeUpdate|executeLargeUpdate|execute|addBatch|prepareStatement"
        r"|prepareCall|createQuery|createNativeQuery|queryForObject|queryForList|queryForMap"
        r"|query|update)\s*\(",
        "jdbc",
        "sql_injection",
        "first",
    ),
    (
        r"\bnew\s+(?:java\.io\.)?(?:FileInputStream|FileOutputStream|FileReader|FileWriter"
        r"|RandomAccessFile|PrintWriter)\s*\(",
        "java.io",
        "path_traversal",
        "first",
    ),
    (r"\bFiles\.\w+\s*\(", "java.nio.Files", "path_traversal", "first"),
]
_CSHARP_SINKS = [
    (r"\bProcess\.Start\s*\(", "Process.Start", "command_injection", "command-line"),
    (r"\bnew\s+ProcessStartInfo\s*\(", "ProcessStartInfo", "command_injection", "command-line"),
    (r"\bFileName\s*=(?![=>])", "ProcessStartInfo", "command_injection", "assign-program"),
    (r"\bArguments\s*=(?![=>])", "ProcessStartInfo", "command_injection", "assign-arguments"),
    (r"\bArgumentList\.Add\s*\(", "ProcessStartInfo", "command_injection", "argument"),
    (r"\bnew\s+\w*Command\s*\(", "DbCommand", "sql_injection", "first"),
    (r"\bCommandText\s*=(?![=>])", "DbCommand", "sql_injection", "assign"),
    (
        r"\.(?:ExecuteSqlRaw|ExecuteSqlRawAsync|FromSqlRaw|SqlQueryRaw|ExecuteSqlCommand)\s*\(",
        "EntityFramework",
        "sql_injection",
        "first",
    ),
    (r"\b(?:File|Directory)\.\w+\s*\(", "System.IO", "path_traversal", "first"),
    (
        r"\bnew\s+(?:FileStream|StreamReader|StreamWriter)\s*\(",
        "System.IO",
        "path_traversal",
        "first",
    ),
]
# Role of the first argument and of every later argument for each mode.
_ROLES = {
    "first": ("value", "inert"),
    "assign": ("value", "inert"),
    "command": ("program", "argument"),
    "command-line": ("program", "arguments"),
    "line": ("line", "inert"),
    "argument": ("argument", "argument"),
    "assign-program": ("program", "inert"),
    "assign-arguments": ("arguments", "inert"),
}
_SKIP_ARGUMENT = re.compile(r"^(?:out|ref|in)\s|^(?:null|default)$|=>|->|::")
_SHELLS = frozenset({"sh", "bash", "dash", "zsh", "cmd", "cmd.exe", "powershell", "pwsh"})


def _code_mask(text: str, language: str) -> list[bool]:
    """Return True for every character that is code, not a comment or a literal."""
    mask = [True] * len(text)
    i, n = 0, len(text)
    while i < n:
        start = i
        if text.startswith("//", i):
            i = text.find("\n", i)
            i = n if i < 0 else i
        elif text.startswith("/*", i):
            i = text.find("*/", i + 2)
            i = n if i < 0 else i + 2
        elif text.startswith('"""', i):
            i = text.find('"""', i + 3)
            i = n if i < 0 else i + 3
        elif language == "csharp" and text.startswith(('@"', '$@"', '@$"'), i):
            i = text.find('"', i) + 1
            while i < n and not (text[i] == '"' and text[i + 1 : i + 2] != '"'):
                i += 2 if text[i] == '"' else 1
            i += 1
        elif text[i] in "\"'" or (language == "csharp" and text.startswith('$"', i)):
            quote = '"' if text[i] == "$" else text[i]
            i += 2 if text[i] == "$" else 1
            while i < n and text[i] != quote and text[i] != "\n":
                i += 2 if text[i] == "\\" else 1
            i += 1
        else:
            i += 1
            continue
        for k in range(start, min(i, n)):
            if text[k] != "\n":
                mask[k] = False
    return mask


def _split(
    text: str, mask: list[bool], start: int, closers: str
) -> tuple[list[tuple[int, int]], int]:
    """Return top-level argument spans from ``start`` and the index of the closing character."""
    depth, spans, begin, i = 0, [], start, start
    while i < len(text):
        ch = text[i]
        if mask[i]:
            if ch in "([{":
                depth += 1
            elif ch in ")]}" and depth:
                depth -= 1
            elif depth == 0 and (ch in closers or ch == ","):
                spans.append((begin, i))
                if ch != ",":
                    return spans, i
                begin = i + 1
        i += 1
    return [], -1


def rewrite(text: str, language: str) -> str:
    sinks = _JAVA_SINKS if language == "java" else _CSHARP_SINKS
    hook = "fdaiprove.H.tap" if language == "java" else "global::FdaiProve.H.Tap"
    mask = _code_mask(text, language)
    inserts: dict[int, str] = {}
    for pattern, sink, weakness, mode in sinks:
        for match in re.finditer(pattern, text):
            if not mask[match.start()]:
                continue
            assigned = mode.startswith("assign")
            spans, _ = _split(text, mask, match.end(), ";,)}" if assigned else ")")
            leading, later = _ROLES[mode]
            for position, (begin, end) in enumerate(spans[:1] if assigned else spans):
                argument = text[begin:end].strip()
                if not argument or _SKIP_ARGUMENT.search(argument):
                    continue
                role = leading if position == 0 else later
                first = begin + len(text[begin:end]) - len(text[begin:end].lstrip())
                inserts[first] = inserts.get(first, "") + f'{hook}("{sink}|{weakness}|{role}", '
                inserts[end] = ")" + inserts.get(end, "")
    out, last = [], 0
    for index in sorted(inserts):
        out.append(text[last:index])
        out.append(inserts[index])
        last = index
    out.append(text[last:])
    return "".join(out)


_JAVA_SUPPORT = r"""package fdaiprove;

import java.lang.reflect.*;
import java.util.*;

public final class H {
    public static String target = "";
    public static int line;
    public static String weakness = "";
    public static String hit;
    static final String MARKER = "FDAICANARYXY";
    static final String INERT = "/nonexistent/fdai-inert";

    // Program and arguments of the command being built on this thread, in call order.
    static final ThreadLocal<List<String>> COMMAND = ThreadLocal.withInitial(ArrayList::new);

    @SuppressWarnings("unchecked")
    public static <T> T tap(String sink, T value) {
        String[] parts = sink.split("\\|");
        boolean match = false;
        if (parts[1].equals(weakness) && !parts[2].equals("inert")) {
            if (parts[2].equals("value")) {
                match = Predicates.matches(weakness, tokens(value));
            } else {
                List<String> command = COMMAND.get();
                if (!parts[2].equals("argument")) command.clear();
                if (parts[2].equals("line") && value instanceof String line) {
                    command.addAll(Shell.words(line));
                } else {
                    command.addAll(tokens(value));
                }
                String script = Shell.script(command);
                match = script != null && Shell.unquoted(script);
            }
        }
        if (hit == null && match && atSite()) hit = parts[0];
        return (T) inert(value);
    }

    static boolean atSite() {
        return StackWalker.getInstance().walk(frames -> frames
            .filter(f -> !f.getClassName().startsWith("fdaiprove."))
            .findFirst()
            .map(f -> target.equals(f.getFileName()) && f.getLineNumber() == line)
            .orElse(false));
    }

    static List<String> tokens(Object value) {
        List<String> out = new ArrayList<>();
        if (value instanceof String[] items) out.addAll(Arrays.asList(items));
        else if (value instanceof Collection<?> items) {
            for (Object item : items) out.add(String.valueOf(item));
        }
        else if (value != null) out.add(String.valueOf(value));
        return out;
    }

    static Object inert(Object value) {
        if (value instanceof String) return INERT;
        if (value instanceof String[] items) {
            String[] copy = new String[items.length];
            Arrays.fill(copy, INERT);
            return copy;
        }
        if (value instanceof List<?> items) {
            return new ArrayList<>(Collections.nCopies(items.size(), INERT));
        }
        if (value instanceof java.io.File) return new java.io.File(INERT);
        if (value instanceof java.nio.file.Path) return java.nio.file.Path.of(INERT);
        return value;
    }
}

final class Predicates {
    static boolean matches(String weakness, List<String> tokens) {
        String joined = String.join(" ", tokens);
        switch (weakness) {
            case "sql_injection":
                return joined.contains("x'" + H.MARKER) && !joined.contains("x''" + H.MARKER)
                    && !joined.contains("x\\'" + H.MARKER);
            case "path_traversal":
                return joined.contains("../../" + H.MARKER);
            default:
                return false;
        }
    }
}

final class Shell {
    static final Set<String> SHELLS = Set.of(
        "sh", "bash", "dash", "zsh", "cmd", "cmd.exe", "powershell", "pwsh");

    // The one argument a shell runs as its command, or null when no shell runs one. Later
    // elements are positional parameters ($0, $1, ...) that the shell never parses.
    static String script(List<String> argv) {
        Set<String> flags = Set.of("-c", "/c", "/C", "-Command");
        if (argv.size() < 3 || !SHELLS.contains(name(argv.get(0)))
                || !flags.contains(argv.get(1))) {
            return null;
        }
        return argv.get(2);
    }

    // Runtime.exec(String) splits on whitespace only, with no quoting.
    static List<String> words(String line) {
        List<String> out = new ArrayList<>();
        for (String word : line.trim().split("\\s+")) if (!word.isEmpty()) out.add(word);
        return out;
    }

    static String name(String program) {
        int cut = Math.max(program.lastIndexOf('/'), program.lastIndexOf('\\'));
        String base = program.substring(cut + 1);
        return base.toLowerCase(Locale.ROOT);
    }

    static boolean unquoted(String value) {
        Character quote = null;
        for (int i = 0; i < value.length(); i++) {
            char ch = value.charAt(i);
            if (quote != null) {
                if (ch == '\\' && quote != '\'') i++;
                else if (ch == quote) quote = null;
                continue;
            }
            if (ch == '"' || ch == '\'') {
                quote = ch;
                continue;
            }
            if (value.startsWith(H.MARKER, i) && value.substring(0, i).matches("(?s).*[;&|]\\s*")) {
                return true;
            }
        }
        return false;
    }
}
"""

_JAVA_RUNNER = r"""package fdaiprove;

import java.lang.reflect.*;
import java.util.*;

public final class Runner {
    static String value;

    public static void main(String[] args) throws Exception {
        H.target = args[0];
        H.line = Integer.parseInt(args[1]);
        H.weakness = args[2];
        value = args[3];
        java.io.PrintStream out = System.out;
        System.setOut(new java.io.PrintStream(java.io.OutputStream.nullOutputStream()));
        System.setErr(new java.io.PrintStream(java.io.OutputStream.nullOutputStream()));
        int calls = 0;
        for (int i = 4; i < args.length && H.hit == null && calls < 200; i++) {
            Class<?> type;
            try {
                type = Class.forName(args[i], false, Runner.class.getClassLoader());
            } catch (Throwable error) {
                continue;
            }
            List<Executable> members = new ArrayList<>();
            members.addAll(Arrays.asList(type.getDeclaredConstructors()));
            members.addAll(Arrays.asList(type.getDeclaredMethods()));
            for (Executable member : members) {
                if (H.hit != null || calls++ >= 200) break;
                invoke(type, member);
            }
        }
        out.println(H.hit == null ? "{}" : "{\"sink\": \"" + H.hit + "\"}");
        out.flush();
        System.exit(0);
    }

    static void invoke(Class<?> type, Executable member) {
        Thread thread = new Thread(() -> {
            try {
                member.setAccessible(true);
                Object[] values = arguments(member.getParameterTypes());
                if (member instanceof Constructor<?> constructor) {
                    if (!Modifier.isAbstract(type.getModifiers())) constructor.newInstance(values);
                } else {
                    Method method = (Method) member;
                    boolean shared = Modifier.isStatic(method.getModifiers());
                    Object receiver = shared ? null : instance(type);
                    method.invoke(receiver, values);
                }
            } catch (Throwable error) {
                // Only recorded hook hits matter.
            }
        });
        thread.setDaemon(true);
        thread.start();
        try {
            thread.join(2000);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
        }
    }

    static Object instance(Class<?> type) {
        for (Constructor<?> constructor : type.getDeclaredConstructors()) {
            try {
                constructor.setAccessible(true);
                return constructor.newInstance(arguments(constructor.getParameterTypes()));
            } catch (Throwable error) {
                // Try the next constructor.
            }
        }
        return null;
    }

    static Object[] arguments(Class<?>[] types) {
        Object[] values = new Object[types.length];
        for (int i = 0; i < types.length; i++) values[i] = canary(types[i], 0);
        return values;
    }

    static Object canary(Class<?> type, int depth) {
        if (type == String.class || type == Object.class || type == CharSequence.class) {
            return value;
        }
        if (type == String[].class) return new String[] {value};
        if (type == boolean.class) return false;
        if (type == char.class) return 'x';
        if (type.isPrimitive()) {
            if (type == long.class) return 0L;
            if (type == double.class) return 0.0d;
            if (type == float.class) return 0.0f;
            if (type == short.class) return (short) 0;
            return type == byte.class ? (byte) 0 : 0;
        }
        if (type == Optional.class) return Optional.of(value);
        if (type.isAssignableFrom(ArrayList.class)) return new ArrayList<>(List.of(value));
        if (type.isAssignableFrom(HashMap.class)) {
            return new HashMap<Object, Object>() {
                @Override
                public Object get(Object key) {
                    return value;
                }

                @Override
                public Object getOrDefault(Object key, Object fallback) {
                    return value;
                }
            };
        }
        if (type.isInterface() && depth < 3) {
            return Proxy.newProxyInstance(Runner.class.getClassLoader(), new Class<?>[] {type},
                (proxy, method, args) -> method.getDeclaringClass() == Object.class
                    ? (method.getName().equals("equals") ? proxy == args[0]
                        : method.getName().equals("hashCode") ? System.identityHashCode(proxy)
                        : "canary")
                    : canary(method.getReturnType(), depth + 1));
        }
        return null;
    }
}
"""

_CSHARP_SUPPORT = r"""namespace FdaiProve
{
    using System;
    using System.Collections;
    using System.Collections.Generic;
    using System.Diagnostics;
    using System.IO;
    using System.Linq;
    using System.Reflection;
    using System.Threading.Tasks;

    public static class H
    {
        public static string Target = "";
        public static int Line;
        public static string Weakness = "";
        public static volatile string Hit;
        public const string Marker = "FDAICANARYXY";
        const string Inert = "/nonexistent/fdai-inert";
        static readonly HashSet<string> Shells = new HashSet<string>
            { "sh", "bash", "dash", "zsh", "cmd", "cmd.exe", "powershell", "pwsh" };

        // Program and arguments of the command being built on this thread, in call order.
        [ThreadStatic] static List<string> command;

        public static T Tap<T>(string sink, T value)
        {
            var parts = sink.Split('|');
            var match = false;
            if (parts[1] == Weakness && parts[2] != "inert")
            {
                if (parts[2] == "value")
                {
                    match = Matches(Tokens(value));
                }
                else
                {
                    if (command == null || parts[2] == "program") command = new List<string>();
                    if (parts[2] == "arguments" && value is string line)
                    {
                        command.AddRange(Words(line));
                    }
                    else
                    {
                        command.AddRange(Tokens(value));
                    }
                    var script = Script(command);
                    match = script != null && Unquoted(script);
                }
            }
            if (Hit == null && match && AtSite()) Hit = parts[0];
            return (T)InertOf(value);
        }

        static bool AtSite()
        {
            foreach (var frame in new StackTrace(true).GetFrames())
            {
                var type = frame.GetMethod()?.DeclaringType;
                if (type != null && type.Namespace == "FdaiProve") continue;
                var file = frame.GetFileName();
                return file != null && Path.GetFileName(file) == Target
                    && frame.GetFileLineNumber() == Line;
            }
            return false;
        }

        static List<string> Tokens(object value)
        {
            if (value is string text) return new List<string> { text };
            if (value is IEnumerable items)
            {
                return items.Cast<object>().Select(Convert.ToString).ToList();
            }
            return value == null ? new List<string>() : new List<string> { value.ToString() };
        }

        static object InertOf(object value)
        {
            switch (value)
            {
                case string _: return Inert;
                case string[] items: return Enumerable.Repeat(Inert, items.Length).ToArray();
                case List<string> items: return Enumerable.Repeat(Inert, items.Count).ToList();
                case FileInfo _: return new FileInfo(Inert);
                case DirectoryInfo _: return new DirectoryInfo(Inert);
                default: return value;
            }
        }

        static bool Matches(List<string> tokens)
        {
            var joined = string.Join(" ", tokens);
            switch (Weakness)
            {
                case "sql_injection":
                    return joined.Contains("x'" + Marker) && !joined.Contains("x''" + Marker)
                        && !joined.Contains("x\\'" + Marker);
                case "path_traversal":
                    return joined.Contains("../../" + Marker);
                default:
                    return false;
            }
        }

        // The one argument a shell runs as its command, or null when no shell runs one. Later
        // elements are positional parameters that the shell never parses.
        static string Script(List<string> argv)
        {
            var flags = new[] { "-c", "/c", "/C", "-Command" };
            if (argv.Count < 3 || !Shells.Contains(Name(argv[0])) || !flags.Contains(argv[1]))
            {
                return null;
            }
            return argv[2];
        }

        // Split one .NET argument string the way ProcessStartInfo does: quotes group, then vanish.
        static IEnumerable<string> Words(string text)
        {
            var word = new System.Text.StringBuilder();
            var quoted = false;
            var started = false;
            for (var i = 0; i < text.Length; i++)
            {
                var ch = text[i];
                if (ch == '\\' && i + 1 < text.Length && text[i + 1] == '"')
                {
                    word.Append('"');
                    started = true;
                    i++;
                }
                else if (ch == '"')
                {
                    quoted = !quoted;
                    started = true;
                }
                else if (char.IsWhiteSpace(ch) && !quoted)
                {
                    if (started) yield return word.ToString();
                    word.Clear();
                    started = false;
                }
                else
                {
                    word.Append(ch);
                    started = true;
                }
            }
            if (started) yield return word.ToString();
        }

        static string Name(string program)
        {
            var cut = Math.Max(program.LastIndexOf('/'), program.LastIndexOf('\\'));
            return program.Substring(cut + 1).ToLowerInvariant();
        }

        static bool Unquoted(string value)
        {
            char? quote = null;
            for (var i = 0; i < value.Length; i++)
            {
                var ch = value[i];
                if (quote != null)
                {
                    if (ch == '\\' && quote != '\'') i++;
                    else if (ch == quote) quote = null;
                    continue;
                }
                if (ch == '"' || ch == '\'')
                {
                    quote = ch;
                    continue;
                }
                if (string.CompareOrdinal(value, i, Marker, 0, Marker.Length) == 0
                    && System.Text.RegularExpressions.Regex.IsMatch(
                        value.Substring(0, i), @"[;&|]\s*$"))
                {
                    return true;
                }
            }
            return false;
        }
    }

    public class Stub : DispatchProxy
    {
        protected override object Invoke(MethodInfo method, object[] args)
        {
            return method.ReturnType == typeof(void) ? null : Runner.Canary(method.ReturnType);
        }
    }

    public static class Runner
    {
        static string Value = "";

        public static int Main(string[] args)
        {
            H.Target = args[0];
            H.Line = int.Parse(args[1]);
            H.Weakness = args[2];
            Value = args[3];
            var stdout = Console.Out;
            Console.SetOut(TextWriter.Null);
            Console.SetError(TextWriter.Null);
            var calls = 0;
            const BindingFlags all = BindingFlags.Public | BindingFlags.NonPublic
                | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly;
            foreach (var type in typeof(Runner).Assembly.GetTypes())
            {
                if (type.Namespace == "FdaiProve" || type.IsInterface
                    || type.ContainsGenericParameters)
                {
                    continue;
                }
                var members = type.GetConstructors(all).Cast<MethodBase>()
                    .Concat(type.GetMethods(all)
                        .Where(m => !m.IsAbstract && !m.ContainsGenericParameters));
                foreach (var member in members)
                {
                    if (H.Hit != null || calls++ >= 200) break;
                    Invoke(type, member);
                }
            }
            stdout.WriteLine(H.Hit == null ? "{}" : "{\"sink\": \"" + H.Hit + "\"}");
            stdout.Flush();
            Environment.Exit(0);
            return 0;
        }

        static void Invoke(Type type, MethodBase member)
        {
            var call = Task.Run(() =>
            {
                try
                {
                    var values = member.GetParameters()
                        .Select(p => Canary(p.ParameterType)).ToArray();
                    object result;
                    if (member is ConstructorInfo constructor)
                    {
                        if (type.IsAbstract) return;
                        result = constructor.Invoke(values);
                    }
                    else
                    {
                        var receiver = member.IsStatic ? null : Instance(type);
                        result = member.Invoke(receiver, values);
                    }
                    if (result is Task task) task.Wait(2000);
                }
                catch (Exception)
                {
                    // Only recorded hook hits matter.
                }
            });
            call.Wait(2000);
        }

        static object Instance(Type type)
        {
            if (type.IsAbstract) return null;
            const BindingFlags any = BindingFlags.Public | BindingFlags.NonPublic
                | BindingFlags.Instance;
            foreach (var constructor in type.GetConstructors(any))
            {
                try
                {
                    return constructor.Invoke(constructor.GetParameters()
                        .Select(p => Canary(p.ParameterType)).ToArray());
                }
                catch (Exception)
                {
                    // Try the next constructor.
                }
            }
            return null;
        }

        internal static object Canary(Type type)
        {
            if (type.IsByRef) type = type.GetElementType();
            if (type == typeof(string) || type == typeof(object)) return Value;
            if (type == typeof(string[])) return new[] { Value };
            if (type.IsAssignableFrom(typeof(List<string>))) return new List<string> { Value };
            if (type.IsAssignableFrom(typeof(Dictionary<string, string>)))
            {
                return new Dictionary<string, string> { [""] = Value };
            }
            if (type.IsValueType) return Activator.CreateInstance(type);
            if (type.IsInterface && !type.ContainsGenericParameters)
            {
                var create = typeof(DispatchProxy).GetMethods()
                    .First(m => m.Name == "Create" && m.GetGenericArguments().Length == 2);
                try
                {
                    return create.MakeGenericMethod(type, typeof(Stub)).Invoke(null, null);
                }
                catch (Exception)
                {
                    return null;
                }
            }
            var empty = type.GetConstructor(Type.EmptyTypes);
            try
            {
                return empty?.Invoke(null);
            }
            catch (Exception)
            {
                return null;
            }
        }
    }
}
"""


def _bounded(
    command: list[str], *, cwd: Path, timeout: int, env: dict[str, str]
) -> tuple[str, str]:
    """Run one toolchain step and return (status, stdout)."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed toolchain argv inside the sandbox
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "timed_out", ""
    except OSError:
        return "no_toolchain", ""
    return ("ok" if done.returncode == 0 else "failed"), done.stdout[:OUTPUT_BYTES].decode(
        "utf-8", "replace"
    )


# The sandbox mounts a private tmpfs at /tmp.
_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/scratch", "TMPDIR": "/tmp", "LANG": "C.UTF-8"}  # noqa: S108
_JVM = ["-Xmx256m", "-Xss1m", "-XX:+UseSerialGC", "-XX:TieredStopAtLevel=1", "-XX:-UsePerfData"]


def _java(work: Path, file: Path, target: dict[str, object], java: Path) -> dict[str, object]:
    javac = java.parent / "javac"
    sources = work / "src"
    classes = work / "classes"
    for folder in (sources / "fdaiprove", classes):
        folder.mkdir(parents=True)
    (sources / file.name).write_text(rewrite(file.read_text("utf-8"), "java"), "utf-8")
    (sources / "fdaiprove" / "H.java").write_text(_JAVA_SUPPORT, "utf-8")
    (sources / "fdaiprove" / "Runner.java").write_text(_JAVA_RUNNER, "utf-8")
    status, _ = _bounded(
        [
            str(javac),
            *(f"-J{flag}" for flag in _JVM),
            "-g",
            "-nowarn",
            "-proc:none",
            "-encoding",
            "UTF-8",
            "-d",
            str(classes),
            str(sources / file.name),
            str(sources / "fdaiprove" / "H.java"),
            str(sources / "fdaiprove" / "Runner.java"),
        ],
        cwd=work,
        timeout=COMPILE_SECONDS,
        env=_ENV,
    )
    if status != "ok":
        return {
            "outcome": "not_proven",
            "reason": "timed_out" if status == "timed_out" else "compile_failed",
        }
    names = sorted(
        str(path.relative_to(classes).with_suffix("")).replace(os.sep, ".")
        for path in classes.rglob("*.class")
        if path.relative_to(classes).parts[0] != "fdaiprove"
    )
    return _run(
        [str(java), *_JVM, "-cp", str(classes), "fdaiprove.Runner", file.name,
         str(target["line"]), str(target["weakness_class"]),
         VALUES[str(target["weakness_class"])], *names],
        work,
        _ENV,
    )  # fmt: skip


def _newest(folder: Path) -> Path | None:
    def key(path: Path) -> tuple[int, ...]:
        return tuple(int(part) for part in re.findall(r"\d+", path.name))

    entries = (
        sorted((p for p in folder.glob("*") if p.is_dir()), key=key) if folder.is_dir() else []
    )
    return entries[-1] if entries else None


def _csharp(work: Path, file: Path, target: dict[str, object], dotnet: Path) -> dict[str, object]:
    root = dotnet.parent
    sdk = _newest(root / "sdk")
    pack = _newest(root / "packs" / "Microsoft.NETCore.App.Ref")
    runtime = _newest(root / "shared" / "Microsoft.NETCore.App")
    compiler = sdk / "Roslyn" / "bincore" / "csc.dll" if sdk else None
    references = sorted(pack.glob("ref/net*/*.dll")) if pack else []
    if compiler is None or not compiler.is_file() or not references or runtime is None:
        return {"outcome": "not_proven", "reason": "no_toolchain"}
    env = {
        **_ENV,
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_NOLOGO": "1",
        "DOTNET_gcServer": "0",
        "DOTNET_GCHeapHardLimit": "0x20000000",
        "DOTNET_TieredPGO": "0",
        "DOTNET_EnableWriteXorExecute": "0",
        "DOTNET_GCRegionRange": "0x40000000",
    }
    source = work / file.name
    source.write_text(rewrite(file.read_text("utf-8"), "csharp"), "utf-8")
    (work / "FdaiProve.cs").write_text(_CSHARP_SUPPORT, "utf-8")
    app = work / "fdai-prove.dll"
    status, _ = _bounded(
        [
            str(dotnet), str(compiler), "-nologo", "-noconfig", "-nostdlib+", "-target:exe",
            "-main:FdaiProve.Runner", "-debug:portable", "-langversion:latest",
            "-nullable:disable", "-nowarn:CS0162,CS0168,CS0219,CS8632,CS1998",
            f"-out:{app}", *(f"-r:{path}" for path in references), str(source),
            str(work / "FdaiProve.cs"),
        ],
        cwd=work,
        timeout=COMPILE_SECONDS,
        env=env,
    )  # fmt: skip
    if status != "ok":
        return {
            "outcome": "not_proven",
            "reason": "timed_out" if status == "timed_out" else "compile_failed",
        }
    tfm = re.sub(r"^(\d+\.\d+).*", r"net\1", runtime.name)
    (work / "fdai-prove.runtimeconfig.json").write_text(
        json.dumps(
            {
                "runtimeOptions": {
                    "tfm": tfm,
                    "framework": {"name": "Microsoft.NETCore.App", "version": runtime.name},
                }
            }
        ),
        "utf-8",
    )
    return _run(
        [str(dotnet), "exec", str(app), file.name, str(target["line"]),
         str(target["weakness_class"]), VALUES[str(target["weakness_class"])]],
        work,
        env,
    )  # fmt: skip


def _run(command: list[str], work: Path, env: dict[str, str]) -> dict[str, object]:
    status, stdout = _bounded(command, cwd=work, timeout=RUN_SECONDS, env=env)
    if status != "ok":
        return {
            "outcome": "not_proven",
            "reason": "timed_out" if status == "timed_out" else "run_failed",
        }
    for line in stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and isinstance(item.get("sink"), str):
            return {"outcome": "proven", "reason": "canary_reached_sink", "sink": item["sink"]}
        if isinstance(item, dict):
            return {"outcome": "not_proven", "reason": "canary_not_observed"}
    return {"outcome": "not_proven", "reason": "no_result"}


def prove(root: Path, target: dict[str, object], toolchain: Path) -> dict[str, object]:
    language = target.get("language")
    if target.get("weakness_class") not in VALUES or language not in {"java", "csharp"}:
        return {"outcome": "not_proven", "reason": "unsupported_class"}
    file = (root / str(target["path"])).resolve()
    if not file.is_relative_to(root.resolve()) or not file.is_file():
        return {"outcome": "not_proven", "reason": "outside_source"}
    if not toolchain.is_file():
        return {"outcome": "not_proven", "reason": "no_toolchain"}
    with tempfile.TemporaryDirectory(prefix="fdai-prove-") as scratch:
        work = Path(scratch)
        if language == "java":
            return _java(work, file, target, toolchain)
        return _csharp(work, file, target, toolchain)


def main() -> int:
    root, targets_path, toolchain = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    targets = json.loads(targets_path.read_text("utf-8"))
    for target in targets:
        try:
            result = prove(root, target, toolchain)
        except Exception:  # noqa: BLE001 - one target never stops the others
            result = {"outcome": "not_proven", "reason": "harness_error"}
        print(json.dumps({"issue_id": target["issue_id"], **result}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
