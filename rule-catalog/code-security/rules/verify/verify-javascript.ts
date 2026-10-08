// Deliberately vulnerable TypeScript fixture for FDAI verifier rules. Never imported or executed.
import * as child_process from "child_process";
import * as fs from "fs";
import { Request, Response } from "express";

export async function search(req: Request, res: Response): Promise<void> {
  const term: string = String(req.query.q);
  // ruleid: fdai.verify.js.sql-injection
  const rows = await sequelize.query(`SELECT * FROM products WHERE name LIKE '%${term}%'`);
  // ok: fdai.verify.js.sql-injection
  const safe = await sequelize.query("SELECT * FROM products WHERE name LIKE ?", { replacements: [term] });
  res.json({ rows, safe });
}

export function archive(req: Request, res: Response): void {
  const target: string = req.body.target;
  // ruleid: fdai.verify.js.command-injection
  child_process.execSync(`tar czf /tmp/out.tgz ${target}`);
  // ruleid: fdai.verify.js.path-traversal
  fs.unlinkSync(`/srv/uploads/${req.params.file}`);
  res.end();
}
