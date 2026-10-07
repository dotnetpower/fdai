// Deliberately vulnerable fixture for FDAI verifier rules. Never imported or executed.
const child_process = require("child_process");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

app.get("/ping", (req, res) => {
  const host = req.query.host;
  // ruleid: fdai.verify.js.command-injection
  child_process.exec("ping -c 1 " + host);
  // ok: fdai.verify.js.command-injection
  child_process.exec("ping -c 1 " + parseInt(req.query.count));
  // ok: fdai.verify.js.command-injection
  child_process.exec("uptime");
});

app.post("/calc", (req, res) => {
  // ruleid: fdai.verify.js.code-injection
  res.send(String(eval(req.body.expression)));
  // ok: fdai.verify.js.code-injection
  res.send(String(eval("1 + 1")));
  const script = `${req.body.script}`;
  // ruleid: fdai.verify.js.code-injection
  vm.runInNewContext(script, {});
});

app.get("/orders", async (req, res) => {
  const name = req.query.name;
  // ruleid: fdai.verify.js.sql-injection
  await db.query("SELECT * FROM orders WHERE name = '" + name + "'");
  // ok: fdai.verify.js.sql-injection
  await db.query("SELECT * FROM orders WHERE name = ?", [name]);
  // ok: fdai.verify.js.sql-injection
  await db.query("SELECT * FROM orders WHERE id = " + Number(req.query.id));
  const local = "archived";
  // ok: fdai.verify.js.sql-injection
  await db.query("SELECT * FROM orders WHERE state = '" + local + "'");
});

app.get("/files", (req, res) => {
  // ruleid: fdai.verify.js.path-traversal
  fs.readFile("/srv/files/" + req.params.name, (err, data) => res.send(data));
  // ok: fdai.verify.js.path-traversal
  fs.readFile("/srv/files/" + path.basename(req.params.name), (err, data) => res.send(data));
});

function offline(config) {
  // ok: fdai.verify.js.command-injection
  child_process.exec("tar xf " + config.archive);
}
