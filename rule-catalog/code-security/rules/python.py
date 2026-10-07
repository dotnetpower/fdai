# Test fixture for python.yaml. Synthetic code; never executed.
import hashlib
import os
import pickle
import subprocess

import requests
import yaml
from flask import Flask, request, send_file

app = Flask(__name__)


def sql(cur, user_id):
    # ruleid: fdai.python.sql-string-built-query
    cur.execute(f"SELECT * FROM users WHERE id = {user_id}")
    # ruleid: fdai.python.sql-string-built-query
    cur.execute("SELECT * FROM users WHERE id = %s" % user_id)
    # ok: fdai.python.sql-string-built-query
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))


def commands(cmd):
    # ruleid: fdai.python.subprocess-shell-true
    subprocess.run(cmd, shell=True)
    # ok: fdai.python.subprocess-shell-true
    subprocess.run("ls -l", shell=True)
    # ok: fdai.python.subprocess-shell-true
    subprocess.run(["ls", cmd])
    # ruleid: fdai.python.os-system
    os.system(cmd)
    # ok: fdai.python.os-system
    os.system("true")


def evaluate(expr):
    # ruleid: fdai.python.eval-exec
    eval(expr)
    # ok: fdai.python.eval-exec
    eval("1 + 1")


def load(blob, text):
    # ruleid: fdai.python.pickle-load
    pickle.loads(blob)
    # ruleid: fdai.python.yaml-unsafe-load
    yaml.load(text)
    # ok: fdai.python.yaml-unsafe-load
    yaml.load(text, Loader=yaml.SafeLoader)
    # ok: fdai.python.yaml-unsafe-load
    yaml.safe_load(text)


def network(url):
    # ruleid: fdai.python.tls-verify-disabled
    requests.get(url, verify=False)
    # ok: fdai.python.tls-verify-disabled
    requests.get(url, timeout=5)


def digest(data):
    # ruleid: fdai.python.weak-hash
    hashlib.md5(data)
    # ok: fdai.python.weak-hash
    hashlib.sha256(data)


@app.route("/file")
def read_file():
    name = request.args.get("name")
    # ruleid: fdai.python.path-from-request
    return open(name).read()


@app.route("/file-safe")
def read_file_safe():
    name = os.path.basename(request.args.get("name"))
    # ok: fdai.python.path-from-request
    return send_file(name)


@app.route("/fetch")
def fetch():
    target = request.args.get("url")
    # ruleid: fdai.python.ssrf-from-request
    return requests.get(target).text


if __name__ == "__main__":
    # ruleid: fdai.python.flask-debug
    app.run(debug=True)
