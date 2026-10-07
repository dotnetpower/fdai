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
}
