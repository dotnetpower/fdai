// Test fixture for javascript.yaml. Synthetic code; never executed.
const cp = require("child_process");
const https = require("https");

function run(cmd, db, el, id) {
  // ruleid: fdai.js.eval
  eval(cmd);
  // ok: fdai.js.eval
  eval("1 + 1");
  // ruleid: fdai.js.child-process-exec
  cp.exec(cmd);
  // ok: fdai.js.child-process-exec
  cp.exec("ls -l");
  // ruleid: fdai.js.inner-html
  el.innerHTML = cmd;
  // ok: fdai.js.inner-html
  el.innerHTML = "<b>static</b>";
  // ruleid: fdai.js.sql-template-query
  db.query(`SELECT * FROM t WHERE id = ${id}`);
  // ok: fdai.js.sql-template-query
  db.query("SELECT * FROM t WHERE id = ?", [id]);
  // ruleid: fdai.js.tls-reject-unauthorized
  https.request({ host: "example.com", rejectUnauthorized: false });
}
