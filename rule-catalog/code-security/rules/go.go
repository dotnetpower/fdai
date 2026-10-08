// Test fixture for go.yaml. Synthetic code; never executed.
package fixture

import (
	"crypto/tls"
	"database/sql"
	"fmt"
	"os/exec"
)

func run(db *sql.DB, script string, id string) {
	// ruleid: fdai.go.shell-command
	exec.Command("sh", "-c", script)
	// ok: fdai.go.shell-command
	exec.Command("sh", "-c", "ls -l")
	// ruleid: fdai.go.sql-sprintf-query
	db.Query(fmt.Sprintf("SELECT * FROM t WHERE id = %s", id))
	// ok: fdai.go.sql-sprintf-query
	db.Query("SELECT * FROM t WHERE id = ?", id)
	// ruleid: fdai.go.tls-insecure-skip-verify
	_ = &tls.Config{InsecureSkipVerify: true}
}
