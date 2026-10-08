// Deliberately vulnerable fixture for FDAI verifier rules. Never compiled or executed.
using System.Diagnostics;
using System.IO;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Data.SqlClient;

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
}
