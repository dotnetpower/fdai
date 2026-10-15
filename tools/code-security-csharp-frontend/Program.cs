using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

internal sealed record Selector(
    [property: JsonPropertyName("role")] string Role,
    [property: JsonPropertyName("symbol")] string Symbol,
    [property: JsonPropertyName("argument_index")] int? ArgumentIndex
);

internal sealed record Rule([property: JsonPropertyName("selectors")] Selector[] Selectors);

internal sealed record Request(
    [property: JsonPropertyName("root")] string Root,
    [property: JsonPropertyName("files")] string[] Files,
    [property: JsonPropertyName("rule")] Rule Rule,
    [property: JsonPropertyName("max_paths")] int MaxPaths,
    [property: JsonPropertyName("max_depth")] int MaxDepth
);

internal sealed record Step(
    [property: JsonPropertyName("role")] string Role,
    [property: JsonPropertyName("path")] string Path,
    [property: JsonPropertyName("line")] int Line,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("context")] string[] Context
);

internal sealed record MethodFact(
    [property: JsonPropertyName("path")] string Path,
    [property: JsonPropertyName("line")] int Line,
    [property: JsonPropertyName("name")] string Name
);

internal sealed record Response(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("compiler_version")] string CompilerVersion,
    [property: JsonPropertyName("paths")] Step[][] Paths,
    [property: JsonPropertyName("methods")] MethodFact[] Methods,
    [property: JsonPropertyName("error_count")] int ErrorCount,
    [property: JsonPropertyName("coverage_limits")] string[] CoverageLimits
);

internal sealed class Analyzer
{
    private readonly CSharpCompilation compilation;
    private readonly Rule rule;
    private readonly int maxPaths;
    private readonly int maxDepth;
    private readonly Dictionary<IMethodSymbol, MethodDeclarationSyntax> methods;
    private readonly List<Step[]> paths = [];
    private readonly HashSet<string> active = [];
    private readonly HashSet<string> coverage = [];

    internal Analyzer(CSharpCompilation compilation, Rule rule, int maxPaths, int maxDepth)
    {
        this.compilation = compilation;
        this.rule = rule;
        this.maxPaths = maxPaths;
        this.maxDepth = maxDepth;
        methods = new Dictionary<IMethodSymbol, MethodDeclarationSyntax>(
            SymbolEqualityComparer.Default);
        foreach (var node in compilation.SyntaxTrees.SelectMany(
            tree => tree.GetRoot().DescendantNodes().OfType<MethodDeclarationSyntax>()))
        {
            var symbol = Model(node).GetDeclaredSymbol(node);
            if (symbol is not null) methods[symbol] = node;
        }
    }

    internal Step[][] Analyze()
    {
        foreach (var pair in methods.OrderBy(item => PathOf(item.Value)).ThenBy(item => LineOf(item.Value)))
        {
            EvaluateMethod(pair.Key, pair.Value, new Dictionary<IParameterSymbol, List<Step>>(
                SymbolEqualityComparer.Default), [], 0);
        }
        return paths
            .OrderBy(path => path[0].Path)
            .ThenBy(path => path[0].Line)
            .ThenBy(path => path[^1].Path)
            .ThenBy(path => path[^1].Line)
            .ToArray();
    }

    internal MethodFact[] MethodFacts => methods
        .Select(item => new MethodFact(
            PathOf(item.Value), LineOf(item.Value), SymbolName(item.Key)))
        .OrderBy(item => item.Path).ThenBy(item => item.Line).ThenBy(item => item.Name)
        .ToArray();
    internal string[] Coverage => coverage.Order().ToArray();

    private SemanticModel Model(SyntaxNode node) => compilation.GetSemanticModel(node.SyntaxTree);

    private static string PathOf(SyntaxNode node) => node.SyntaxTree.FilePath.Replace('\\', '/');

    private static int LineOf(SyntaxNode node) =>
        node.SyntaxTree.GetLineSpan(node.Span).StartLinePosition.Line + 1;

    private static string SymbolName(ISymbol? symbol) => symbol switch
    {
        IMethodSymbol method when method.MethodKind == MethodKind.Constructor =>
            method.ContainingType.ToDisplayString(),
        IMethodSymbol method => $"{method.ContainingType.ToDisplayString()}.{method.Name}",
        IPropertySymbol property => $"{property.ContainingType.ToDisplayString()}.{property.Name}",
        IFieldSymbol field => $"{field.ContainingType.ToDisplayString()}.{field.Name}",
        INamedTypeSymbol type => type.ToDisplayString(),
        _ => "",
    };

    private static bool Matches(string name, string expected)
    {
        if (name == expected || name.EndsWith("." + expected, StringComparison.Ordinal)) return true;
        var terminal = name.Split('.').LastOrDefault() ?? "";
        return !expected.Contains('.') && terminal == expected;
    }

    private List<Step>? Source(ExpressionSyntax expression, string[] context)
    {
        var model = Model(expression);
        var symbol = model.GetSymbolInfo(expression).Symbol;
        var name = SymbolName(symbol);
        if (!rule.Selectors.Any(item => item.Role == "source" && Matches(name, item.Symbol)))
            return null;
        return [new Step("source", PathOf(expression), LineOf(expression), name, context)];
    }

    private List<Step>? EvaluateMethod(
        IMethodSymbol symbol,
        MethodDeclarationSyntax method,
        Dictionary<IParameterSymbol, List<Step>> arguments,
        string[] context,
        int depth)
    {
        var identity = symbol.ToDisplayString() + "|" + string.Join("/", context);
        if (depth >= maxDepth || !active.Add(identity))
        {
            coverage.Add("csharp.recursion-or-depth-limit");
            return null;
        }
        try
        {
            var state = new Dictionary<ISymbol, List<Step>>(SymbolEqualityComparer.Default);
            foreach (var parameter in symbol.Parameters)
            {
                if (arguments.TryGetValue(parameter, out var passed)) state[parameter] = passed;
                var syntax = method.ParameterList.Parameters
                    .FirstOrDefault(item => item.Identifier.ValueText == parameter.Name);
                var sourceAttribute = syntax?.AttributeLists.SelectMany(item => item.Attributes)
                    .Select(item => SymbolName(Model(item).GetSymbolInfo(item).Symbol))
                    .FirstOrDefault(name => rule.Selectors.Any(
                        selector => selector.Role == "source" && Matches(name, selector.Symbol)));
                if (sourceAttribute is not null)
                {
                    state[parameter] = [new Step(
                        "source", PathOf(syntax!), LineOf(syntax!), sourceAttribute, context)];
                }
            }
            if (method.Body is null)
                return method.ExpressionBody is null
                    ? null
                    : Evaluate(method.ExpressionBody.Expression, state, context, depth);
            List<Step>? returned = null;
            foreach (var statement in method.Body.Statements)
            {
                switch (statement)
                {
                    case LocalDeclarationStatementSyntax local:
                        foreach (var variable in local.Declaration.Variables)
                        {
                            var declared = Model(variable).GetDeclaredSymbol(variable);
                            var value = variable.Initializer is null
                                ? null
                                : Evaluate(variable.Initializer.Value, state, context, depth);
                            if (declared is not null && value is not null) state[declared] = value;
                        }
                        break;
                    case ExpressionStatementSyntax expression:
                        if (expression.Expression is AssignmentExpressionSyntax assignment)
                        {
                            var target = Model(assignment.Left).GetSymbolInfo(assignment.Left).Symbol;
                            var value = Evaluate(assignment.Right, state, context, depth);
                            if (target is not null && value is not null) state[target] = value;
                        }
                        else Evaluate(expression.Expression, state, context, depth);
                        break;
                    case ReturnStatementSyntax result when result.Expression is not null:
                        returned = Evaluate(result.Expression, state, context, depth);
                        break;
                    case IfStatementSyntax conditional:
                        if (conditional.Condition.IsKind(SyntaxKind.FalseLiteralExpression)) break;
                        returned ??= EvaluateStatement(conditional.Statement, state, context, depth);
                        if (conditional.Else is not null)
                            returned ??= EvaluateStatement(conditional.Else.Statement, state, context, depth);
                        break;
                    case ThrowStatementSyntax:
                        return returned;
                }
            }
            return returned;
        }
        finally
        {
            active.Remove(identity);
        }
    }

    private List<Step>? EvaluateStatement(
        StatementSyntax statement,
        Dictionary<ISymbol, List<Step>> state,
        string[] context,
        int depth) => statement switch
        {
            ReturnStatementSyntax result when result.Expression is not null =>
                Evaluate(result.Expression, state, context, depth),
            ExpressionStatementSyntax expression => Evaluate(expression.Expression, state, context, depth),
            BlockSyntax block => block.Statements
                .Select(item => EvaluateStatement(item, state, context, depth))
                .FirstOrDefault(item => item is not null),
            _ => null,
        };

    private List<Step>? Evaluate(
        ExpressionSyntax expression,
        Dictionary<ISymbol, List<Step>> state,
        string[] context,
        int depth)
    {
        var direct = Source(expression, context);
        if (direct is not null) return direct;
        var model = Model(expression);
        var symbol = model.GetSymbolInfo(expression).Symbol;
        if (symbol is not null && state.TryGetValue(symbol, out var tracked)) return tracked;
        if (expression is InvocationExpressionSyntax invocation)
            return EvaluateInvocation(invocation, state, context, depth);
        if (expression is ObjectCreationExpressionSyntax creation)
            return EvaluateCreation(creation, state, context, depth);
        foreach (var child in expression.ChildNodes().OfType<ExpressionSyntax>())
        {
            var value = Evaluate(child, state, context, depth);
            if (value is not null) return value;
        }
        return null;
    }

    private List<Step>? EvaluateInvocation(
        InvocationExpressionSyntax invocation,
        Dictionary<ISymbol, List<Step>> state,
        string[] context,
        int depth)
    {
        var model = Model(invocation);
        var method = model.GetSymbolInfo(invocation).Symbol as IMethodSymbol;
        var name = SymbolName(method);
        var values = invocation.ArgumentList.Arguments
            .Select(item => Evaluate(item.Expression, state, context, depth)).ToArray();
        if (rule.Selectors.Any(item => item.Role == "sanitizer" && Matches(name, item.Symbol)))
            return null;
        foreach (var selector in rule.Selectors.Where(item => item.Role == "sink" && Matches(name, item.Symbol)))
        {
            var index = selector.ArgumentIndex ?? 0;
            if (index < values.Length && values[index] is { } value) RecordSink(value, invocation, name, context);
        }
        if (method is not null)
        {
            var target = methods.Keys.FirstOrDefault(item => SymbolEqualityComparer.Default.Equals(item, method));
            if (target is not null)
            {
                var call = new Step("call", PathOf(invocation), LineOf(invocation), name, [.. context, name]);
                var bindings = new Dictionary<IParameterSymbol, List<Step>>(SymbolEqualityComparer.Default);
                for (var index = 0; index < Math.Min(target.Parameters.Length, values.Length); index++)
                    if (values[index] is { } value) bindings[target.Parameters[index]] = [.. value, call];
                var returned = EvaluateMethod(target, methods[target], bindings, [.. context, name], depth + 1);
                if (returned is not null)
                    return [.. returned, new Step("return", PathOf(invocation), LineOf(invocation), name, context)];
            }
        }
        return values.FirstOrDefault(item => item is not null);
    }

    private List<Step>? EvaluateCreation(
        ObjectCreationExpressionSyntax creation,
        Dictionary<ISymbol, List<Step>> state,
        string[] context,
        int depth)
    {
        var constructor = Model(creation).GetSymbolInfo(creation).Symbol as IMethodSymbol;
        var name = constructor is null ? creation.Type.ToString() : SymbolName(constructor);
        var values = creation.ArgumentList?.Arguments
            .Select(item => Evaluate(item.Expression, state, context, depth)).ToArray() ?? [];
        foreach (var selector in rule.Selectors.Where(item => item.Role == "sink" && Matches(name, item.Symbol)))
        {
            var index = selector.ArgumentIndex ?? 0;
            if (index < values.Length && values[index] is { } value) RecordSink(value, creation, name, context);
        }
        return values.FirstOrDefault(item => item is not null);
    }

    private void RecordSink(List<Step> value, SyntaxNode sink, string name, string[] context)
    {
        if (paths.Count >= maxPaths)
        {
            coverage.Add("csharp.path-limit");
            return;
        }
        paths.Add([.. value, new Step("sink", PathOf(sink), LineOf(sink), name, context)]);
    }
}

internal static class Program
{
    private static MetadataReference[] References() =>
        ((string?)AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") ?? "")
            .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries)
            .Select(path => MetadataReference.CreateFromFile(path))
            .ToArray();

    public static async Task<int> Main()
    {
        var request = await JsonSerializer.DeserializeAsync<Request>(Console.OpenStandardInput())
            ?? throw new InvalidDataException("request is required");
        var root = Path.GetFullPath(request.Root);
        var trees = new List<SyntaxTree>();
        foreach (var relative in request.Files.Order())
        {
            var path = Path.GetFullPath(Path.Combine(root, relative));
            if (!path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.Ordinal)
                || new FileInfo(path).LinkTarget is not null)
                throw new InvalidDataException("source escapes root or is linked");
            var source = await File.ReadAllTextAsync(path);
            trees.Add(CSharpSyntaxTree.ParseText(source, path: relative));
        }
        var compilation = CSharpCompilation.Create(
            "FdaiAnalysis",
            trees,
            References(),
            new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary)
                .WithConcurrentBuild(false)
                .WithOptimizationLevel(OptimizationLevel.Debug)
        );
        var analyzer = new Analyzer(compilation, request.Rule, request.MaxPaths, request.MaxDepth);
        var paths = analyzer.Analyze();
        var errors = compilation.GetDiagnostics().Count(item => item.Severity == DiagnosticSeverity.Error);
        var response = new Response(
            "1.0.0",
            typeof(CSharpCompilation).Assembly.GetName().Version?.ToString(3) ?? "0.0.0",
            paths,
            analyzer.MethodFacts,
            errors,
            analyzer.Coverage
        );
        await JsonSerializer.SerializeAsync(Console.OpenStandardOutput(), response);
        return 0;
    }
}
