import com.sun.source.tree.CompilationUnitTree;
import com.sun.source.tree.MethodInvocationTree;
import com.sun.source.tree.MethodTree;
import com.sun.source.util.JavacTask;
import com.sun.source.util.SourcePositions;
import com.sun.source.util.TreePathScanner;
import com.sun.source.util.Trees;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import javax.lang.model.element.Element;
import javax.lang.model.element.ExecutableElement;
import javax.lang.model.element.TypeElement;
import javax.lang.model.type.TypeMirror;
import javax.tools.Diagnostic;
import javax.tools.DiagnosticCollector;
import javax.tools.JavaCompiler;
import javax.tools.JavaFileObject;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;

public final class FdaiJavaSymbols {
    private static String quote(String value) {
        StringBuilder result = new StringBuilder("\"");
        for (int index = 0; index < value.length(); index++) {
            char current = value.charAt(index);
            switch (current) {
                case '\\' -> result.append("\\\\");
                case '"' -> result.append("\\\"");
                case '\n' -> result.append("\\n");
                case '\r' -> result.append("\\r");
                case '\t' -> result.append("\\t");
                default -> {
                    if (current < 0x20) result.append(String.format("\\u%04x", (int) current));
                    else result.append(current);
                }
            }
        }
        return result.append('"').toString();
    }

    private static String symbol(Element element) {
        if (!(element instanceof ExecutableElement executable)) return "";
        Element owner = executable.getEnclosingElement();
        String ownerName = owner instanceof TypeElement type
            ? type.getQualifiedName().toString()
            : owner.toString();
        return ownerName + "." + executable.getSimpleName();
    }

    public static void main(String[] args) throws IOException {
        if (args.length != 3 || !args[1].equals("--files-from")) {
            throw new IllegalArgumentException("root and --files-from manifest are required");
        }
        Path root = Path.of(args[0]).toRealPath(LinkOption.NOFOLLOW_LINKS);
        List<Path> sources = new ArrayList<>();
        Path manifest = Path.of(args[2]).toRealPath(LinkOption.NOFOLLOW_LINKS);
        if (!Files.isRegularFile(manifest) || Files.size(manifest) > 2_000_000) {
            throw new IllegalArgumentException("source manifest is not a bounded regular file");
        }
        List<String> requested = Files.readAllLines(manifest);
        if (requested.isEmpty() || requested.size() > 2_000) {
            throw new IllegalArgumentException("source manifest count is outside bounds");
        }
        for (String relative : requested) {
            if (relative.length() > 1_024 || relative.indexOf('\n') >= 0 || relative.indexOf('\r') >= 0) {
                throw new IllegalArgumentException("source manifest path is outside bounds");
            }
            Path source = root.resolve(relative).normalize();
            if (!source.startsWith(root) || Files.isSymbolicLink(source) || !Files.isRegularFile(source)) {
                throw new IllegalArgumentException("source escapes root or is not a regular file");
            }
            sources.add(source);
        }
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) throw new IllegalStateException("JDK compiler is unavailable");
        DiagnosticCollector<JavaFileObject> diagnostics = new DiagnosticCollector<>();
        try (StandardJavaFileManager files = compiler.getStandardFileManager(diagnostics, Locale.ROOT, null)) {
            Iterable<? extends JavaFileObject> units = files.getJavaFileObjectsFromPaths(sources);
            JavacTask task = (JavacTask) compiler.getTask(
                null,
                files,
                diagnostics,
                List.of("-proc:none", "-Xlint:none", "-implicit:none", "-g:none"),
                null,
                units
            );
            List<CompilationUnitTree> parsed = new ArrayList<>();
            task.parse().forEach(parsed::add);
            task.analyze();
            Trees trees = Trees.instance(task);
            SourcePositions positions = trees.getSourcePositions();
            List<String> methods = new ArrayList<>();
            List<String> calls = new ArrayList<>();
            for (CompilationUnitTree unit : parsed) {
                Path source = Path.of(unit.getSourceFile().toUri()).toRealPath();
                String relative = root.relativize(source).toString().replace('\\', '/');
                String sourceText = Files.readString(source);
                new TreePathScanner<Void, Void>() {
                    private long line(com.sun.source.tree.Tree tree) {
                        long offset = positions.getStartPosition(unit, tree);
                        if (offset < 0) return 0;
                        long result = 1;
                        int end = (int) Math.min(offset, sourceText.length());
                        for (int index = 0; index < end; index++) {
                            if (sourceText.charAt(index) == '\n') result++;
                        }
                        return result;
                    }

                    @Override
                    public Void visitMethod(MethodTree tree, Void unused) {
                        Element element = trees.getElement(getCurrentPath());
                        TypeMirror type = element == null ? null : element.asType();
                        methods.add(
                            "{\"path\":" + quote(relative)
                                + ",\"line\":" + line(tree)
                                + ",\"name\":" + quote(tree.getName().toString())
                                + ",\"symbol\":" + quote(symbol(element))
                                + ",\"type\":" + quote(type == null ? "" : type.toString()) + "}"
                        );
                        return super.visitMethod(tree, unused);
                    }

                    @Override
                    public Void visitMethodInvocation(MethodInvocationTree tree, Void unused) {
                        Element element = trees.getElement(getCurrentPath());
                        TypeMirror type = trees.getTypeMirror(getCurrentPath());
                        calls.add(
                            "{\"path\":" + quote(relative)
                                + ",\"line\":" + line(tree)
                                + ",\"text\":" + quote(tree.getMethodSelect().toString())
                                + ",\"symbol\":" + quote(symbol(element))
                                + ",\"type\":" + quote(type == null ? "" : type.toString()) + "}"
                        );
                        return super.visitMethodInvocation(tree, unused);
                    }
                }.scan(unit, null);
            }
            long errors = diagnostics.getDiagnostics().stream()
                .filter(item -> item.getKind() == Diagnostic.Kind.ERROR)
                .count();
            System.out.print("{\"schema_version\":\"1.0.0\",\"compiler_version\":"
                + quote(System.getProperty("java.version"))
                + ",\"methods\":[" + String.join(",", methods)
                + "],\"calls\":[" + String.join(",", calls)
                + "],\"error_count\":" + errors + "}");
        }
    }
}
