// Deliberately vulnerable fixture for FDAI verifier rules. Never compiled or executed.
import java.io.File;
import java.io.FileInputStream;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.Statement;
import javax.servlet.http.HttpServletRequest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;

public class VerifyFixture {
    private Connection connection;
    private JdbcTemplate jdbc;

    public void servlet(HttpServletRequest request) throws Exception {
        String host = request.getParameter("host");
        // ruleid: fdai.verify.java.command-injection
        Runtime.getRuntime().exec("ping -c 1 " + host);
        // ok: fdai.verify.java.command-injection
        Runtime.getRuntime().exec(new String[] {"ping", "-c", "1", "localhost"});
        String id = request.getParameter("id");
        Statement statement = connection.createStatement();
        // ruleid: fdai.verify.java.sql-injection
        statement.executeQuery("SELECT * FROM orders WHERE id = '" + id + "'");
        // ok: fdai.verify.java.sql-injection
        statement.executeQuery("SELECT * FROM orders WHERE id = " + Integer.parseInt(id));
        // ruleid: fdai.verify.java.path-traversal
        FileInputStream in = new FileInputStream("/srv/files/" + request.getParameter("name"));
        in.close();
    }

    @GetMapping("/orders")
    public Object orders(@RequestParam String name, @RequestParam int page) {
        // ruleid: fdai.verify.java.sql-injection
        Object rows = jdbc.queryForList("SELECT * FROM orders WHERE name = '" + name + "'");
        // ok: fdai.verify.java.sql-injection
        Object paged = jdbc.queryForList("SELECT * FROM orders LIMIT 10 OFFSET " + page * 10);
        // ok: fdai.verify.java.sql-injection
        Object safe = jdbc.queryForList("SELECT * FROM orders WHERE name = ?", name);
        return rows;
    }

    public File local(String configured) {
        // ok: fdai.verify.java.path-traversal
        return new File(configured);
    }

    @GetMapping("/download")
    public Object download(@RequestParam("file") String file) {
        // ruleid: fdai.verify.java.path-traversal
        return Paths.get("/srv/files", file);
    }

    public void helperResults(HttpServletRequest request) throws Exception {
        String input = request.getParameter("name");
        // ruleid: fdai.verify.java.path-traversal
        new java.io.File(input);
        // ruleid: fdai.verify.java.path-traversal
        new java.io.File("/srv/files", input);
        // ruleid: fdai.verify.java.path-traversal
        new java.io.FileInputStream(input);
        // ruleid: fdai.verify.java.path-traversal
        new java.io.FileOutputStream(input, false);
        // ruleid: fdai.verify.java.path-traversal
        new java.io.FileReader(input);
        // ok: fdai.verify.java.path-traversal
        new java.io.FileReader("/srv/files/fixed");
        String constant = constantResult(input);
        // ok: fdai.verify.java.path-traversal
        new java.io.FileReader(constant);
        String unknown = unresolvedResult(input);
        // A miss is abstention, not a claim that this helper or its sink is safe.
        // ok: fdai.verify.java.path-traversal
        new java.io.FileReader(unknown);
        // ruleid: fdai.verify.java.path-traversal
        new java.io.FileReader(input);
    }

    private String constantResult(String input) {
        int offset = 4;
        if ((2 * 6) - offset > 5) return "fixed";
        return input;
    }

    private String unresolvedResult(String input) {
        return input;
    }
}
