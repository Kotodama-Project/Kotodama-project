"""Constrain an entire Task Codex process, not just its model shell commands.

No host authentication bytes are copied. The operator supplies a dedicated
Task credential home; the model's inner profile cannot read that home.
Unsupported sandbox/profile implementations fail before a model invocation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import uuid

from .protocol import SwarmError


def refuse(condition, code):
    if not condition:
        raise SwarmError(code, "confidential Task execution refused")


def config(name, value):
    return ["-c", name+"="+json.dumps(value, ensure_ascii=True)]


def table(values):
    return "{"+",".join(json.dumps(str(key))+"="+json.dumps(value) for key, value in values.items())+"}"


def profile(name, paths, *, network):
    return ["-c", "permissions."+name+".filesystem="+table({":root":"deny", **paths}),
            "-c", "permissions."+name+".network.enabled="+("true" if network else "false")]


def require_observed_profile(observed, active, allowed_paths):
    """Validate effective permissions, never just the selected profile name."""
    refuse(isinstance(observed,dict) and set(observed)=={"type","file_system","network"} and
           observed["type"]=="managed" and observed["network"]=="restricted" and
           active=={"id":"task-input"}, "CONFIDENTIAL_RUNTIME_POLICY_UNVERIFIED")
    filesystem=observed["file_system"]
    refuse(isinstance(filesystem,dict) and set(filesystem)=={"type","entries"} and
           filesystem["type"]=="restricted" and isinstance(filesystem["entries"],list),
           "CONFIDENTIAL_RUNTIME_POLICY_UNVERIFIED")
    actual=[]
    for entry in filesystem["entries"]:
        refuse(isinstance(entry,dict) and set(entry)=={"path","access"}, "CONFIDENTIAL_RUNTIME_POLICY_UNVERIFIED")
        target=entry["path"]
        if target=={"type":"special","value":{"kind":"root"}}:
            key=":root"
        else:
            refuse(isinstance(target,dict) and set(target)=={"type","path"} and target["type"]=="path" and
                   isinstance(target["path"],str) and Path(target["path"]).is_absolute(), "CONFIDENTIAL_RUNTIME_POLICY_UNVERIFIED")
            key=str(Path(target["path"]).resolve(strict=True))
        actual.append((key,entry["access"]))
    expected={(":root","deny"),*((str(Path(name).resolve(strict=True)),access) for name,access in allowed_paths.items())}
    refuse(set(actual)==expected and all(access in ("read","deny") for _,access in actual),
           "CONFIDENTIAL_RUNTIME_POLICY_UNVERIFIED")


def runtime_paths(executable):
    paths = {name:"read" for name in ("/bin","/lib","/lib64","/usr/bin","/usr/lib","/usr/lib64") if Path(name).exists()}
    paths.update({str(Path(name).resolve(strict=True)):"read" for name in list(paths)})
    selected = Path(executable).resolve(strict=True)
    with selected.open("rb") as stream:
        refuse(stream.read(4) == b"\x7fELF", "CONFIDENTIAL_NATIVE_LINUX_CLI_REQUIRED")
    paths[str(selected)] = "read"
    # Require the native CLI so the owned PID and sandbox executable are exact;
    # do not widen access to a package manager's installation/store.
    return paths


def dedicated_home(selected, environment):
    refuse(isinstance(selected, (str, Path)) and Path(selected).is_absolute(), "CONFIDENTIAL_TASK_HOME_REQUIRED")
    home = Path(selected)
    for entry in (home, *home.parents):
        info = entry.lstat()
        refuse(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), "CONFIDENTIAL_TASK_HOME_REFUSED")
    home = home.resolve(strict=True)
    ambient = Path(environment.get("CODEX_HOME", str(Path.home()/".codex"))).expanduser().resolve()
    refuse(home != ambient and home != (Path.home()/".codex").resolve(), "CONFIDENTIAL_SHARED_AUTH_REFUSED")
    info = home.stat()
    refuse(info.st_uid == os.getuid() and info.st_mode & 0o077 == 0, "CONFIDENTIAL_TASK_HOME_REFUSED")
    auth = home/"auth.json"
    info = auth.lstat()
    refuse(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_nlink == 1 and
           info.st_uid == os.getuid() and info.st_mode & 0o077 == 0, "CONFIDENTIAL_AUTH_FILE_REQUIRED")
    return home


class ConfidentialScope:
    def __init__(self, directory, executable, *, task_codex_home=None, environment=None):
        refuse(os.name == "posix", "CONFIDENTIAL_SCOPE_REQUIRES_POSIX")
        self.root = Path(directory).resolve(strict=True)
        self.executable = str(Path(executable).resolve(strict=True))
        self.environment = dict(os.environ if environment is None else environment)
        self.codex_home = dedicated_home(task_codex_home, self.environment)
        refuse(not self.root.is_relative_to(self.codex_home) and not self.codex_home.is_relative_to(self.root),
               "CONFIDENTIAL_TASK_HOME_REFUSED")
        self.work = self.root/"work"
        self.home = self.root/"isolated-home"
        for folder in (self.work, self.home):
            folder.mkdir(mode=0o700)
        paths = runtime_paths(self.executable)
        self.input_paths = {**paths,str(self.work):"read"}
        self.inner = profile("task-input", self.input_paths, network=False)
        # The dedicated CLI owns its credential refresh and runtime metadata.
        # There is no alias to the interactive user's credential store.
        external = {str(self.codex_home):"write"}
        for name in ("/etc/ssl/certs","/etc/resolv.conf","/etc/hosts","/etc/nsswitch.conf","/dev/null","/dev/urandom"):
            if Path(name).exists():
                external[name] = "read"
        self.outer = profile("task-runtime", {**paths,**external,str(self.root):"write"}, network=True)
        allowed = ("PATH","LANG","LC_ALL","SSL_CERT_FILE","SSL_CERT_DIR")
        self.env = {key:value for key,value in self.environment.items() if key in allowed}
        self.env.update(HOME=str(self.home),CODEX_HOME=str(self.codex_home),TMPDIR=str(self.root/"tmp"),
                        XDG_CONFIG_HOME=str(self.home/".config"),XDG_CACHE_HOME=str(self.home/".cache"))
        (self.root/"tmp").mkdir(mode=0o700)
        self.proof = None

    def sandbox(self, name, settings, command):
        return [self.executable, "sandbox", "--permission-profile", name, "--cd", str(self.work),
                "--include-managed-config", *settings, "--", *command]

    def preflight(self):
        nonce = uuid.uuid4().hex
        allowed = self.work/"probe-input"
        denied = self.root/"probe-private"
        sibling = self.root.parent/("probe-outside-"+nonce)
        for file in (allowed, denied, sibling):
            file.write_text(nonce, encoding="utf-8")
        # Only synthetic files are probed. Never try to read a real credential.
        script = 'test "$(cat "$1")" = "$3" && ! cat "$2" >/dev/null 2>&1 && printf "%s" "$3"'
        try:
            for name, settings, forbidden in (("task-runtime",self.outer,sibling),("task-input",self.inner,denied)):
                result = subprocess.run(self.sandbox(name,settings,[str(Path("/bin/sh").resolve(strict=True)),"-c",script,"probe",str(allowed),str(forbidden),nonce]),
                                        cwd=self.work,env=self.env,capture_output=True,timeout=15)
                refuse(result.returncode == 0 and result.stdout.decode("utf-8","replace") == nonce,
                       "CONFIDENTIAL_SANDBOX_UNAVAILABLE")
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SwarmError("CONFIDENTIAL_SANDBOX_UNAVAILABLE", "sandbox probe did not complete") from exc
        finally:
            # Exactly the three synthetic files owned by this preflight.
            for file in (allowed, denied, sibling):
                file.unlink(missing_ok=True)
        self.proof = {"kind":"task_synthetic_permission_probe_v1","outer_read_denied":True,"inner_metadata_read_denied":True,
                      "model_called":False}
        return dict(self.proof)

    def wrap(self, command):
        refuse(self.proof is not None, "CONFIDENTIAL_PREFLIGHT_REQUIRED")
        args = list(command)
        # A custom profile replaces legacy -s; do not let that legacy preset
        # reopen all reads. Separate non-filesystem tools are explicitly off.
        index = args.index("-s")
        del args[index:index+2]
        args.extend(["--ignore-user-config","--ignore-rules","--strict-config",
                     *config("default_permissions","task-input"),*self.inner,
                     *config("project_doc_max_bytes",0),*config("web_search","disabled"),
                     *config("memories.use_memories",False),*config("memories.generate_memories",False)])
        for feature in ("apps","plugins","browser_use","browser_use_external","browser_use_full_cdp_access",
                        "in_app_browser","view_image","shell_tool","unified_exec","multi_agent","multi_agent_v2",
                        "memories","hooks","image_generation","goals","code_mode","code_mode_host",
                        "external_agent_memory_import","shell_snapshot","remote_plugin"):
            args.extend(config("features."+feature,False))
        return self.sandbox("task-runtime",self.outer,args)
