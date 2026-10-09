// Deliberately vulnerable fixture for FDAI verifier rules. Never compiled or executed.
using System.Diagnostics;
using System.IO;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Data.SqlClient;
using Microsoft.Data.Sqlite;
using Microsoft.AspNetCore.Http;

public class VerifyFixtureController : Controller
{
    private SqlConnection connection;

    public IActionResult Ping()
    {
        string host = Request.Query["host"];
        // ruleid: fdai.verify.csharp.command-injection
        Process.Start("ping", "-c 1 " + host);
        // ok: fdai.verify.csharp.command-injection
        Process.Start("uptime");
        return Ok();
    }

    public IActionResult Orders([FromQuery] string name, [FromQuery] int page)
    {
        // ruleid: fdai.verify.csharp.sql-injection
        var command = new SqlCommand("SELECT * FROM Orders WHERE Name = '" + name + "'", connection);
        // ok: fdai.verify.csharp.sql-injection
        var paged = new SqlCommand("SELECT * FROM Orders ORDER BY Id OFFSET " + page * 10, connection);
        // ok: fdai.verify.csharp.sql-injection
        var safe = new SqlCommand("SELECT * FROM Orders WHERE Name = @name", connection);
        return Ok();
    }

    [HttpGet("search")]
    public IActionResult Search(string keyword, int page)
    {
        var query = $"SELECT * FROM Products WHERE Name LIKE '%{keyword}%'";
        // ruleid: fdai.verify.csharp.sql-injection
        var products = context.Products.FromSql(query).ToList();
        // ok: fdai.verify.csharp.sql-injection
        var paged = context.Products.FromSql($"SELECT * FROM Products OFFSET {page}").ToList();
        return Ok(products);
    }

    public string Helper(string configured)
    {
        // ok: fdai.verify.csharp.sql-injection
        return context.Products.FromSql(configured).ToString();
    }

    public IActionResult Download()
    {
        string file = Request.Query["file"];
        // ruleid: fdai.verify.csharp.path-traversal
        var bytes = File.ReadAllBytes("/srv/files/" + file);
        // ok: fdai.verify.csharp.path-traversal
        var safe = File.ReadAllBytes("/srv/files/" + Path.GetFileName(file));
        return Ok();
    }

    [HttpPost]
    public IActionResult Upload(IFormFile upload)
    {
        // ruleid: fdai.verify.csharp.path-traversal
        var path = Path.Combine("/srv/uploads", upload.FileName);
        // ruleid: fdai.verify.csharp.path-traversal
        using var file = new FileStream(path, FileMode.Create);
        // ok: fdai.verify.csharp.path-traversal
        var safe = Path.Combine("/srv/uploads", Path.GetFileName(upload.FileName));
        // ok: fdai.verify.csharp.path-traversal
        var safeBytes = System.IO.File.ReadAllBytes(safe);
        // ruleid: fdai.verify.csharp.path-traversal
        var unsafeBytes = System.IO.File.ReadAllBytes(path);
        return Ok();
    }

    [HttpGet]
    public IActionResult SqliteSearch(string name, int page)
    {
        // ruleid: fdai.verify.csharp.sql-injection
        using var command = new SqliteCommand("SELECT * FROM Orders WHERE Name = '" + name + "'", connection);
        // ok: fdai.verify.csharp.sql-injection
        using var safe = new SqliteCommand("SELECT * FROM Orders WHERE Name = @name", connection);
        // ok: fdai.verify.csharp.sql-injection
        using var numeric = new SqliteCommand("SELECT * FROM Orders WHERE Id = " + int.Parse(name), connection);
        // ok: fdai.verify.csharp.sql-injection
        using var typed = new SqliteCommand("SELECT * FROM Orders WHERE Id = " + page, connection);
        // ruleid: fdai.verify.csharp.sql-injection
        using var filename = new SqlCommand("SELECT * FROM Files WHERE Name = '" + Path.GetFileName(name) + "'", connection);
        return Ok();
    }

    [HttpGet]
    public IActionResult Shell(string command)
    {
        var process = new Process();
        process.StartInfo.FileName = "/bin/sh";
        // ruleid: fdai.verify.csharp.command-injection
        process.StartInfo.Arguments = "-c " + command;
        // ok: fdai.verify.csharp.command-injection
        process.StartInfo.Arguments = "-c uptime";
        // ruleid: fdai.verify.csharp.command-injection
        process.StartInfo.FileName = command;
        var info = new ProcessStartInfo();
        info.FileName = "/bin/sh";
        // ruleid: fdai.verify.csharp.command-injection
        info.Arguments = "-c " + command;
        // ruleid: fdai.verify.csharp.command-injection
        info.FileName = command;
        // ruleid: fdai.verify.csharp.command-injection
        var initialized = new ProcessStartInfo { FileName = "/bin/sh", Arguments = "-c " + command };
        // ruleid: fdai.verify.csharp.command-injection
        var executable = new ProcessStartInfo { FileName = command };
        // ok: fdai.verify.csharp.command-injection
        var fixedCommand = new ProcessStartInfo { FileName = "/bin/sh", Arguments = "-c uptime" };
        // ruleid: fdai.verify.csharp.command-injection
        Process.Start("/bin/sh", "-c " + Path.GetFileName(command));
        // ok: fdai.verify.csharp.command-injection
        Process.Start("/bin/sh", "-c echo " + int.Parse(command));
        var unrelated = new DisplayOptions();
        // ok: fdai.verify.csharp.command-injection
        unrelated.Arguments = command;
        // ok: fdai.verify.csharp.command-injection
        unrelated.FileName = command;
        return Ok();
    }

    public IActionResult Configured()
    {
        var info = new ProcessStartInfo();
        // ok: fdai.verify.csharp.command-injection
        info.Arguments = "-c uptime";
        // ok: fdai.verify.csharp.command-injection
        info.FileName = "/bin/sh";
        return Ok();
    }
}
