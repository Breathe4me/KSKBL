"""Real HTTPS on 127.0.0.1 only; throwaway certificates, no system trust changes or GUI."""

import argparse
import json
import os
import shutil
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from build_manifest import file_hash


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # never log headers or bodies, even fabricated credentials

    def respond(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        self.server.receipts.append({"method": "GET", "path": path})
        data = {
            "/health": {"ok": True},
            "/api/v1/users/self/profile": {"id": 123},
            "/api/v1/courses": [{"id": 1, "name": "TEST1001 Synthetic", "course_code": "TEST1001"}],
            "/api/v1/courses/1/assignments": [
                {
                    "id": 2,
                    "name": "Synthetic HTTPS task",
                    "due_at": None,
                    "html_url": "",
                    "submission": {"workflow_state": "unsubmitted"},
                }
            ],
            "/api/v1/courses/1/quizzes": [],
            "/api/v1/courses/1/discussion_topics": [],
        }
        self.respond(
            data[path] if path in data else {"error": "local_test_route_missing"},
            200 if path in data else 404,
        )

    def do_POST(self):
        path = urlsplit(self.path).path
        self.server.receipts.append({"method": "POST", "path": path})
        count = int(self.headers.get("Content-Length", "0"))
        if not 0 <= count <= 65536:
            self.respond({}, 413)
            return
        self.rfile.read(count)
        if path == "/pushplus":
            self.respond({"code": 200})
        elif path == "/ai/chat/completions":
            self.respond(
                {"choices": [{"message": {"content": '{"local_test":true}'}, "finish_reason": "stop"}]}
            )
        else:
            self.respond({}, 404)


def certificates(directory, openssl):
    def run(*args):
        subprocess.run(  # noqa: S603 - exact local OpenSSL and fixed synthetic certificate arguments
            [str(openssl), *args],
            cwd=directory,
            check=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )  # noqa: S603 - local installed OpenSSL, fixed test args

    run(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "test-ca.key",
        "-out",
        "test-ca.pem",
        "-days",
        "1",
        "-subj",
        "/CN=CDA Synthetic Local TLS Test CA",
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
    )
    for name, host, serial in (
        ("trusted", "IP:127.0.0.1,DNS:localhost", "123"),
        ("wrong_hostname", "DNS:wrong.invalid", "124"),
    ):
        run(
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            name + ".key",
            "-out",
            name + ".csr",
            "-subj",
            "/CN=CDA Synthetic TLS Server",
        )
        (directory / (name + ".ext")).write_text(
            "[leaf]\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\nsubjectAltName="
            + host
            + "\n",
            encoding="ascii",
        )
        run(
            "x509",
            "-req",
            "-in",
            name + ".csr",
            "-CA",
            "test-ca.pem",
            "-CAkey",
            "test-ca.key",
            "-set_serial",
            serial,
            "-days",
            "1",
            "-extfile",
            name + ".ext",
            "-extensions",
            "leaf",
            "-out",
            name + ".pem",
        )
    run(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        "untrusted.key",
        "-out",
        "untrusted.pem",
        "-days",
        "1",
        "-subj",
        "/CN=CDA Synthetic Untrusted Server",
        "-addext",
        "subjectAltName=IP:127.0.0.1",
        "-addext",
        "basicConstraints=critical,CA:FALSE",
    )


def verify(output, openssl, candidate=None, release=False):
    project = Path(__file__).resolve().parents[1]
    output = Path(output).resolve()
    if not output.is_relative_to(
        project / ("release-prep" if release else "qa-export" if candidate else "reports")
    ):
        raise ValueError("Expected isolated test output within the project")
    if candidate:
        candidate = Path(candidate).resolve()
        proof = candidate / ("evidence/FROZEN_TLS_CHECK.json" if release else "FROZEN_TLS_CHECK.json")
        if (
            not candidate.is_relative_to(project / ("release-prep" if release else "qa-export"))
            or proof.exists()
        ):
            raise ValueError("Refusing existing proof or unrelated candidate")
    output.mkdir(parents=True, exist_ok=False)
    certs = output / "throwaway-server-certificates"
    certs.mkdir()
    certificates(certs, Path(openssl).resolve())
    servers, threads, ports = [], [], {}
    try:
        for name in ("trusted", "wrong_hostname", "untrusted"):
            # Product URLs intentionally require 443. Preserve that validation in the real Bridge path.
            server = ThreadingHTTPServer(("127.0.0.1", 443 if name == "trusted" else 0), Handler)
            server.daemon_threads = True
            server.receipts = []
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(certs / (name + ".pem"), certs / (name + ".key"))
            server.socket = ctx.wrap_socket(server.socket, server_side=True)
            ports[name] = server.server_port
            servers.append(server)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            threads.append(thread)
        profile = output / "中文独立测试目录"
        profile.mkdir()
        shutil.copyfile(certs / "test-ca.pem", profile / "test-ca.pem")
        (profile / "tls-test-plan.json").write_text(json.dumps(ports), encoding="utf-8")
        if candidate:
            exe = candidate / (
                "payload/CanvasDeadlineAgent/CanvasDeadlineAgent.exe"
                if release
                else "portable/CanvasDeadlineAgent-UI-QA/CanvasDeadlineAgent-UI-QA.exe"
            )
            command = [str(exe)]
        else:
            command = [
                sys.executable,
                "-B",
                "-c",
                "from canvas_agent.app import main; raise SystemExit(main())",
            ]
        command += (["--release-selfcheck", "tls"] if release else ["--tls-check"]) + [
            "--data-dir",
            str(profile),
        ]
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSLKEYLOGFILE")
        }
        env["LOCALAPPDATA"] = str(output / "unused-localappdata")
        # Python source run also uses absolute PYTHONPATH with unrelated cwd; no real user profile.
        env["PYTHONPATH"] = os.pathsep.join(
            str((project / value).resolve()) if not Path(value).is_absolute() else value
            for value in env.get("PYTHONPATH", "").split(os.pathsep)
            if value
        )
        process = subprocess.run(  # noqa: S603 - exact no-window selfcheck, loopback plan only
            command,
            cwd=output,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=80,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )  # noqa: S603
        result_file = profile / "tls-check-result.json"
        result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {}
        record = {
            "status": "passed" if process.returncode == 0 and result.get("status") == "passed" else "failed",
            "create_no_window": True,
            "exit_code": process.returncode,
            "result": result,
            "server_requests": [item for server in servers for item in server.receipts],
            "server_bind": "127.0.0.1:443 trusted; ephemeral ports for rejection cases",
            "system_trust_modified": False,
            "all_four_CA_environment_variables_unset": True,
            "unicode_path_and_unrelated_cwd": True,
        }
        if candidate:
            record["exe_sha256"] = file_hash(exe)
        record["expected_11_cases"] = len(result.get("cases", [])) == 11
        if not record["expected_11_cases"] or not all(case.get("passed") for case in result.get("cases", [])):
            record["status"] = "failed"
        if candidate and result.get("frozen") is not True:
            record["status"] = "failed"
        (output / "PROCESS.json").write_text(
            json.dumps(
                {"exit_code": process.returncode, "stdout": process.stdout, "stderr": process.stderr},
                indent=2,
            ),
            encoding="utf-8",
        )
        target = proof if candidate else output / "ORDINARY_TLS_CHECK.json"
        target.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {"status": record["status"], "proof": str(target), "cases": len(result.get("cases", []))}
            )
        )
        if record["status"] != "passed":
            raise ValueError("Real local HTTPS verification failed; do not build/finalize QA")
        return record
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--openssl", required=True, type=Path)
    args = parser.parse_args()
    if args.release and not args.candidate:
        parser.error("--release requires an isolated candidate")
    verify(args.output, args.openssl, args.candidate, args.release)
