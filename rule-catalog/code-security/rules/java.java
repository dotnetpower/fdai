// Test fixture for java.yaml. Synthetic code; never executed.
import java.io.ObjectInputStream;
import java.sql.Statement;

class Fixture {
    void run(Statement st, String id, String cmd, java.io.InputStream in) throws Exception {
        // ruleid: fdai.java.sql-concatenated-statement
        st.executeQuery("SELECT * FROM t WHERE id = " + id);
        // ruleid: fdai.java.runtime-exec
        Runtime.getRuntime().exec(cmd);
        // ok: fdai.java.runtime-exec
        Runtime.getRuntime().exec("ls");
        // ruleid: fdai.java.object-input-stream
        Object o = new ObjectInputStream(in).readObject();
    }
}
