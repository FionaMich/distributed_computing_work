import json
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont
from pathlib import Path
from typing import Optional, List, Dict
import os

from common import send_json, recv_json, make_address

# Configuration defaults
DEFAULT_PYTHON = sys.executable or "python"
COORDINATOR_SCRIPT = "coordinator.py"
DATA_NODE_SCRIPT = "data_node.py"
CLIENT_SCRIPT = "client.py"
DATA_DIR = Path("data")

# Defaults
DEFAULT_COORDINATOR_HOST = "127.0.0.1"
DEFAULT_COORDINATOR_PORT = 5000
DEFAULT_NODE_COUNT = 3
DEFAULT_NODE_BASE_PORT = 6001
DEFAULT_NODE_HOST = "127.0.0.1"


class ManagedProcess:
    def __init__(self, name: str, cmd: List[str], env: Optional[Dict[str, str]] = None):
        self.name = name
        self.cmd = cmd
        self.env = env or os.environ.copy()
        self.proc: Optional[subprocess.Popen] = None
        self.stdout_queue: "queue.Queue[str]" = queue.Queue()
        self.stderr_queue: "queue.Queue[str]" = queue.Queue()
        self._stop_event = threading.Event()

    def start(self) -> bool:
        if self.proc and self.proc.poll() is None:
            return False
        self.proc = subprocess.Popen(
            self.cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=self.env,
        )
        self._stop_event.clear()
        threading.Thread(target=self._reader, args=(self.proc.stdout, self.stdout_queue), daemon=True).start()
        threading.Thread(target=self._reader, args=(self.proc.stderr, self.stderr_queue), daemon=True).start()
        threading.Thread(target=self._watch_for_exit, daemon=True).start()
        return True

    def _reader(self, pipe, q: "queue.Queue[str]") -> None:
        if pipe is None:
            return
        with pipe:
            for line in iter(pipe.readline, ''):
                q.put(line)
                if self._stop_event.is_set():
                    break

    def stop(self) -> None:
        self._stop_event.set()
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            except Exception:
                pass
        self.proc = None

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _watch_for_exit(self) -> None:
        p = self.proc
        if not p:
            return
        try:
            rc = p.wait()
            self.stderr_queue.put(f"[process:{self.name}] exited with code {rc}\n")
        except Exception:
            pass




class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Distributed Store Control Panel (GROUP THREE)")
        self.geometry("1200x780")
        # Apply modern theme and larger fonts
        self._apply_theme()

        # State
        self.coordinator: Optional[ManagedProcess] = None
        self.nodes: Dict[str, ManagedProcess] = {}
        self.node_ports: Dict[str, int] = {}

        # UI
        self._build_ui()

        # Timers
        self.after(200, self._drain_logs_loop)
        self.after(1000, self._refresh_state_files_loop)

    def _apply_theme(self):
        try:
            style = ttk.Style(self)
            try:
                style.theme_use('clam')
            except Exception:
                pass
            # Increase common fonts
            try:
                for fname in ("TkDefaultFont", "TkTextFont", "TkFixedFont"):
                    f = tkfont.nametofont(fname)
                    f.configure(size=11)
            except Exception:
                pass
            # Modern paddings
            style.configure("TButton", padding=6)
            style.configure("TNotebook.Tab", padding=(12, 6))
            # Dark-ish palette where supported by ttk theme
            for elem in ("TFrame", "TLabel", "TLabelframe", "TLabelframe.Label"):
                style.configure(elem, background="#0f172a", foreground="#e2ecff")
            style.configure("TEntry", fieldbackground="#1e293b", foreground="#e2ecff")
        except Exception:
            # Best-effort theming; continue even if some platforms don't support all options
            pass

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # Top controls frame
        controls = ttk.Frame(self)
        controls.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        for i in range(12):
            controls.columnconfigure(i, weight=1)

        # Coordinator controls
        ttk.Label(controls, text="Coord host:").grid(row=0, column=0, sticky="w")
        self.coord_host_var = tk.StringVar(value=DEFAULT_COORDINATOR_HOST)
        ttk.Entry(controls, textvariable=self.coord_host_var, width=12).grid(row=0, column=1, sticky="w")
        ttk.Label(controls, text="Coord port:").grid(row=0, column=2, sticky="e")
        self.coord_port_var = tk.StringVar(value=str(DEFAULT_COORDINATOR_PORT))
        ttk.Entry(controls, textvariable=self.coord_port_var, width=8).grid(row=0, column=3, sticky="w")
        self.btn_start_coord = ttk.Button(controls, text="Start Coordinator", command=self.start_coordinator)
        self.btn_start_coord.grid(row=0, column=4, padx=4)
        self.btn_stop_coord = ttk.Button(controls, text="Stop Coordinator", command=self.stop_coordinator, state="disabled")
        self.btn_stop_coord.grid(row=0, column=5, padx=4)

        # Node controls
        ttk.Label(controls, text="Nodes:").grid(row=0, column=6, sticky="e")
        self.node_count_var = tk.StringVar(value=str(DEFAULT_NODE_COUNT))
        ttk.Entry(controls, textvariable=self.node_count_var, width=4).grid(row=0, column=7, sticky="w")
        ttk.Label(controls, text="Base port:").grid(row=0, column=8, sticky="e")
        self.node_base_port_var = tk.StringVar(value=str(DEFAULT_NODE_BASE_PORT))
        ttk.Entry(controls, textvariable=self.node_base_port_var, width=6).grid(row=0, column=9, sticky="w")
        self.btn_start_nodes = ttk.Button(controls, text="Start Nodes", command=self.start_nodes)
        self.btn_start_nodes.grid(row=0, column=10, padx=4)
        self.btn_stop_nodes = ttk.Button(controls, text="Stop Nodes", command=self.stop_nodes, state="disabled")
        self.btn_stop_nodes.grid(row=0, column=11, padx=4)

        # Notebook for tabs
        nb = ttk.Notebook(self)
        nb.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)

        # Tab: Operations
        self.tab_ops = ttk.Frame(nb)
        nb.add(self.tab_ops, text="Operations")
        self._build_ops_tab(self.tab_ops)

        # Tab: Logs
        self.tab_logs = ttk.Frame(nb)
        nb.add(self.tab_logs, text="Logs")
        self._build_logs_tab(self.tab_logs)

        # Tab: State Viewer
        self.tab_state = ttk.Frame(nb)
        nb.add(self.tab_state, text="State Viewer")
        self._build_state_tab(self.tab_state)

        # Tab: Failures / Recovery
        self.tab_fail = ttk.Frame(nb)
        nb.add(self.tab_fail, text="Failures / Recovery")
        self._build_failures_tab(self.tab_fail)

    def _build_ops_tab(self, parent: ttk.Frame):
        parent.columnconfigure(0, weight=1)
        form = ttk.Frame(parent)
        form.grid(row=0, column=0, sticky="ew")
        for i in range(10):
            form.columnconfigure(i, weight=1)

        ttk.Label(form, text="Operation:").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        self.op_var = tk.StringVar(value="read_balance")
        self.op_combo = ttk.Combobox(form, textvariable=self.op_var, values=["read_balance", "transfer"], width=14, state="readonly")
        self.op_combo.grid(row=0, column=1, sticky="w")
        self.op_combo.bind("<<ComboboxSelected>>", lambda e: self._update_op_fields())

        # Read Balance fields
        ttk.Label(form, text="Read: Node").grid(row=1, column=0, sticky="e", padx=4)
        self.read_node_var = tk.StringVar(value="N1")
        ttk.Entry(form, textvariable=self.read_node_var, width=6).grid(row=1, column=1, sticky="w")
        ttk.Label(form, text="Account").grid(row=1, column=2, sticky="e")
        self.read_account_var = tk.StringVar(value="A")
        ttk.Entry(form, textvariable=self.read_account_var, width=12).grid(row=1, column=3, sticky="w")

        # Transfer fields
        ttk.Label(form, text="From Node").grid(row=2, column=0, sticky="e", padx=4)
        self.from_node_var = tk.StringVar(value="N1")
        ttk.Entry(form, textvariable=self.from_node_var, width=6).grid(row=2, column=1, sticky="w")
        ttk.Label(form, text="From Account").grid(row=2, column=2, sticky="e")
        self.from_account_var = tk.StringVar(value="A")
        ttk.Entry(form, textvariable=self.from_account_var, width=12).grid(row=2, column=3, sticky="w")

        ttk.Label(form, text="To Node").grid(row=3, column=0, sticky="e", padx=4)
        self.to_node_var = tk.StringVar(value="N2")
        ttk.Entry(form, textvariable=self.to_node_var, width=6).grid(row=3, column=1, sticky="w")
        ttk.Label(form, text="To Account").grid(row=3, column=2, sticky="e")
        self.to_account_var = tk.StringVar(value="B")
        ttk.Entry(form, textvariable=self.to_account_var, width=12).grid(row=3, column=3, sticky="w")

        ttk.Label(form, text="Amount").grid(row=4, column=0, sticky="e", padx=4)
        self.amount_var = tk.StringVar(value="10")
        ttk.Entry(form, textvariable=self.amount_var, width=8).grid(row=4, column=1, sticky="w")

        self.btn_execute = ttk.Button(parent, text="Execute", command=self.execute_operation)
        self.btn_execute.grid(row=5, column=0, sticky="w", padx=4, pady=8)

        # Concurrency demos
        demos = ttk.LabelFrame(parent, text="Concurrency Demos")
        demos.grid(row=2, column=0, sticky="ew", padx=4, pady=4)
        demos.columnconfigure(0, weight=1)
        ttk.Button(demos, text="Run concurrent transfers (3 clients)", command=self.run_concurrent_transfers_demo).grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Button(demos, text="Run conflicting locks demo (2 clients)", command=self.run_conflicting_locks_demo).grid(row=1, column=0, sticky="w", padx=4, pady=2)

        # Results box
        self.result_text = tk.Text(parent, height=14, wrap="none", background="#0b1220", foreground="#cfe3ff", font=("Consolas", 11))
        self.result_text.grid(row=6, column=0, sticky="nsew", pady=(6, 0))
        xscroll = ttk.Scrollbar(parent, orient="horizontal", command=self.result_text.xview)
        xscroll.grid(row=7, column=0, sticky="ew")
        self.result_text.configure(xscrollcommand=xscroll.set)
        parent.rowconfigure(6, weight=1)

        # Initialize visible fields
        self._update_op_fields()

    def _update_op_fields(self):
        # In this simple version we always show all fields; validation is op-specific.
        pass

    def _build_logs_tab(self, parent: ttk.Frame):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=0)
        self.logs_text = tk.Text(parent, wrap="none", state="disabled", background="#0b1220", foreground="#cfe3ff", font=("Consolas", 11))
        self.logs_text.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(parent, orient="vertical", command=self.logs_text.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll = ttk.Scrollbar(parent, orient="horizontal", command=self.logs_text.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        self.logs_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

    def _build_state_tab(self, parent: ttk.Frame):
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=0)

        # Files list
        files_frame = ttk.Frame(parent)
        files_frame.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        ttk.Label(files_frame, text="Data files").grid(row=0, column=0, sticky="w")
        self.files_list = tk.Listbox(files_frame, width=40, height=30)
        self.files_list.grid(row=1, column=0, sticky="nsw")
        self.files_list.bind('<<ListboxSelect>>', self._on_file_select)

        # Content view
        self.state_text = tk.Text(parent, wrap="none", background="#0b1220", foreground="#cfe3ff", font=("Consolas", 11))
        self.state_text.grid(row=0, column=1, sticky="nsew")
        yscroll = ttk.Scrollbar(parent, orient="vertical", command=self.state_text.yview)
        yscroll.grid(row=0, column=2, sticky="ns")
        xscroll = ttk.Scrollbar(parent, orient="horizontal", command=self.state_text.xview)
        xscroll.grid(row=1, column=1, sticky="ew")
        self.state_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

    def _build_failures_tab(self, parent: ttk.Frame):
        parent.columnconfigure(0, weight=1)

        frm = ttk.LabelFrame(parent, text="Crash injection")
        frm.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        for i in range(10):
            frm.columnconfigure(i, weight=1)

        ttk.Label(frm, text="Delay (ms):").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        self.fail_delay_var = tk.StringVar(value="500")
        ttk.Entry(frm, textvariable=self.fail_delay_var, width=8).grid(row=0, column=1, sticky="w")

        ttk.Label(frm, text="Node to crash:").grid(row=0, column=2, sticky="e", padx=4)
        self.fail_node_var = tk.StringVar(value="N2")
        self.fail_node_combo = ttk.Combobox(frm, textvariable=self.fail_node_var, values=["N1", "N2", "N3"], width=6, state="readonly")
        self.fail_node_combo.grid(row=0, column=3, sticky="w")

        # Coordinator failure injection controls
        ttk.Label(frm, text="Coordinator fail at:").grid(row=0, column=4, sticky="e", padx=4)
        self.coord_fail_at_var = tk.StringVar(value="None")
        self.coord_fail_at_combo = ttk.Combobox(frm, textvariable=self.coord_fail_at_var, values=["None", "PREPARE", "BEFORE_COMMIT", "AFTER_COMMIT"], width=16, state="readonly")
        self.coord_fail_at_combo.grid(row=0, column=5, sticky="w")

        ttk.Label(frm, text="Coord fail delay (ms):").grid(row=0, column=6, sticky="e", padx=4)
        self.coord_fail_delay_var = tk.StringVar(value="0")
        ttk.Entry(frm, textvariable=self.coord_fail_delay_var, width=8).grid(row=0, column=7, sticky="w")

        ttk.Button(frm, text="Start transfer, then crash COORDINATOR", command=self.start_transfer_then_crash_coordinator).grid(row=1, column=0, columnspan=3, sticky="w", padx=4, pady=4)
        ttk.Button(frm, text="Start transfer, then crash NODE (selected)", command=self.start_transfer_then_crash_node).grid(row=1, column=3, columnspan=3, sticky="w", padx=4, pady=4)

    # Process management
    def start_coordinator(self):
        try:
            host = self.coord_host_var.get().strip() or DEFAULT_COORDINATOR_HOST
            port = int(self.coord_port_var.get())
            count = int(self.node_count_var.get())
            base_port = int(self.node_base_port_var.get())
        except ValueError:
            messagebox.showerror("Invalid config", "Ports and counts must be integers")
            return
        # Build --nodes spec to match current node controls
        nodes_spec_parts: List[str] = []
        for i in range(count):
            node_id = f"N{i+1}"
            p = base_port + i
            nodes_spec_parts.append(f"{node_id}:{DEFAULT_NODE_HOST}:{p}")
        nodes_spec = ",".join(nodes_spec_parts)
        cmd = [DEFAULT_PYTHON, COORDINATOR_SCRIPT, "--host", host, "--port", str(port), "--nodes", nodes_spec]

        # Build environment for coordinator failure injection
        env = os.environ.copy()
        fail_at = self.coord_fail_at_var.get().strip() if hasattr(self, 'coord_fail_at_var') else "None"
        fail_at_env = "" if not fail_at or fail_at == "None" else fail_at
        fail_delay = self.coord_fail_delay_var.get().strip() if hasattr(self, 'coord_fail_delay_var') else "0"
        if fail_at_env:
            env["COORD_FAIL_AT"] = fail_at_env
        else:
            env.pop("COORD_FAIL_AT", None)
        try:
            delay_int = int(fail_delay or "0")
        except ValueError:
            delay_int = 0
        env["COORD_FAIL_DELAY_MS"] = str(delay_int)

        if self.coordinator is None:
            self.coordinator = ManagedProcess("coordinator", cmd, env=env)
        else:
            # update command/env in case config changed
            self.coordinator.cmd = cmd
            self.coordinator.env = env
        ok = self.coordinator.start()
        if ok:
            self._log(f"[ui] Started coordinator on {host}:{port} with nodes {nodes_spec}\n")
            if fail_at_env:
                self._log(f"[ui] Coordinator failure injection: COORD_FAIL_AT={fail_at_env}, COORD_FAIL_DELAY_MS={delay_int}\n")
            self.btn_start_coord.config(state="disabled")
            self.btn_stop_coord.config(state="normal")
        else:
            messagebox.showwarning("Coordinator", "Coordinator is already running")

    def stop_coordinator(self):
        if self.coordinator:
            self.coordinator.stop()
            self._log("[ui] Stopped coordinator\n")
        self.btn_start_coord.config(state="normal")
        self.btn_stop_coord.config(state="disabled")

    def start_nodes(self):
        try:
            count = int(self.node_count_var.get())
            base_port = int(self.node_base_port_var.get())
        except ValueError:
            messagebox.showerror("Invalid config", "Node count and base port must be integers")
            return
        if self.nodes:
            messagebox.showwarning("Nodes", "Nodes are already running")
            return
        self.node_ports.clear()
        for i in range(count):
            node_id = f"N{i+1}"
            port = base_port + i
            cmd = [DEFAULT_PYTHON, DATA_NODE_SCRIPT, "--node-id", node_id, "--port", str(port)]
            mp = ManagedProcess(f"node-{node_id}", cmd)
            mp.start()
            self.nodes[node_id] = mp
            self.node_ports[node_id] = port
            self._log(f"[ui] Started node {node_id} on {DEFAULT_NODE_HOST}:{port}\n")
        self.btn_start_nodes.config(state="disabled")
        self.btn_stop_nodes.config(state="normal")
        # refresh failures tab node list
        self._refresh_failures_node_list()

    def stop_nodes(self):
        for node_id, mp in list(self.nodes.items()):
            mp.stop()
            self._log(f"[ui] Stopped node {node_id}\n")
        self.nodes.clear()
        self.node_ports.clear()
        self.btn_start_nodes.config(state="normal")
        self.btn_stop_nodes.config(state="disabled")
        # refresh failures tab node list
        self._refresh_failures_node_list()

    # Logs handling
    def _drain_logs_loop(self):
        # Always drain queues, even if processes have already exited, so we
        # still show their last logs and exit codes.
        if self.coordinator:
            self._drain_queue(self.coordinator.stdout_queue, prefix="[coordinator] ")
            self._drain_queue(self.coordinator.stderr_queue, prefix="[coordinator-err] ")
        for node_id, mp in list(self.nodes.items()):
            self._drain_queue(mp.stdout_queue, prefix=f"[node:{node_id}] ")
            self._drain_queue(mp.stderr_queue, prefix=f"[node-err:{node_id}] ")
        self.after(200, self._drain_logs_loop)

    def _drain_queue(self, q: "queue.Queue[str]", prefix: str = "") -> None:
        try:
            while True:
                line = q.get_nowait()
                self._log(prefix + line)
        except queue.Empty:
            pass

    def _log(self, text: str) -> None:
        self.logs_text.configure(state="normal")
        self.logs_text.insert("end", text)
        self.logs_text.see("end")
        self.logs_text.configure(state="disabled")

    # State viewer
    def _refresh_state_files_loop(self):
        try:
            files: List[str] = []
            if DATA_DIR.exists():
                patterns = ["*.json", "*.jsonl", "*.log", "*.txt"]
                matched: List[Path] = []
                for pat in patterns:
                    matched.extend(DATA_DIR.glob(pat))
                for p in sorted(set(matched), key=lambda x: str(x).lower()):
                    files.append(str(p))
            current = list(self.files_list.get(0, "end"))
            if files != current:
                self.files_list.delete(0, "end")
                for f in files:
                    self.files_list.insert("end", f)
        except Exception as e:
            self._log(f"[ui] Error scanning data dir: {e}\n")
        self.after(1500, self._refresh_state_files_loop)

    def _on_file_select(self, event=None):
        sel = self.files_list.curselection()
        if not sel:
            return
        path = self.files_list.get(sel[0])
        try:
            content = Path(path).read_text(encoding="utf-8")
            try:
                parsed = json.loads(content)
                content = json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                pass
            self.state_text.delete("1.0", "end")
            self.state_text.insert("1.0", content)
        except Exception as e:
            messagebox.showerror("Read error", f"Failed to read {path}: {e}")

    # Client operations
    def execute_operation(self):
        op = self.op_var.get()
        if op == "read_balance":
            self._op_read_balance()
        elif op == "transfer":
            self._op_transfer()
        else:
            messagebox.showerror("Operation", f"Unknown operation: {op}")

    def _op_read_balance(self):
        node_id = self.read_node_var.get().strip()
        account = self.read_account_var.get().strip()
        if not node_id or not account:
            messagebox.showerror("Invalid input", "Node and Account are required for read")
            return
        # Determine port
        port = self.node_ports.get(node_id)
        if port is None:
            # Fallback to default mapping by node label
            try:
                idx = int(node_id.replace("N", "")) - 1
                base_port = int(self.node_base_port_var.get())
                port = base_port + idx
            except Exception:
                messagebox.showerror("Node port", f"Unknown node {node_id} and no running node mapping found")
                return
        host = DEFAULT_NODE_HOST
        self._log(f"[ui] READ {account} on {node_id} ({host}:{port})\n")
        threading.Thread(target=self._read_balance_task, args=(host, port, account), daemon=True).start()

    def _read_balance_task(self, host: str, port: int, account: str):
        try:
            with socket.create_connection(make_address(host, port), timeout=5.0) as conn:
                send_json(conn, {"type": "READ", "account_id": account})
                reply = recv_json(conn)
                self._append_result(json.dumps(reply, indent=2) + "\n")
        except Exception as e:
            self._append_result(f"READ failed: {e}\n")

    def _op_transfer(self):
        try:
            coord_host = self.coord_host_var.get().strip() or DEFAULT_COORDINATOR_HOST
            coord_port = int(self.coord_port_var.get())
        except ValueError:
            messagebox.showerror("Invalid input", "Coordinator port must be an integer")
            return
        from_node = self.from_node_var.get().strip()
        from_acc = self.from_account_var.get().strip()
        to_node = self.to_node_var.get().strip()
        to_acc = self.to_account_var.get().strip()
        amount_str = self.amount_var.get().strip()
        if not (from_node and from_acc and to_node and to_acc and amount_str):
            messagebox.showerror("Invalid input", "All transfer fields are required")
            return
        try:
            amount = int(amount_str)
        except ValueError:
            messagebox.showerror("Invalid input", "Amount must be an integer")
            return

        cmd = [
            DEFAULT_PYTHON,
            CLIENT_SCRIPT,
            "--coord-host", coord_host,
            "--coord-port", str(coord_port),
            "--from-node", from_node,
            "--from-account", from_acc,
            "--to-node", to_node,
            "--to-account", to_acc,
            "--amount", str(amount),
        ]
        self._log(f"[ui] Executing transfer via client: {' '.join(cmd)}\n")
        threading.Thread(target=self._run_client_and_show_result, args=(cmd,), daemon=True).start()

    def run_concurrent_transfers_demo(self):
        try:
            coord_host = self.coord_host_var.get().strip() or DEFAULT_COORDINATOR_HOST
            coord_port = int(self.coord_port_var.get())
        except ValueError:
            messagebox.showerror("Invalid input", "Coordinator port must be an integer")
            return
        # Three concurrent transfers, mirroring README demo_concurrent_transfers
        specs = [
            ("C1", {"from_node": "N1", "from_account": "A", "to_node": "N2", "to_account": "B", "amount": 10}),
            ("C2", {"from_node": "N2", "from_account": "B", "to_node": "N1", "to_account": "A", "amount": 10}),
            ("C3", {"from_node": "N3", "from_account": "C", "to_node": "N1", "to_account": "A", "amount": 20}),
        ]
        self._append_result("Starting concurrent transfers (3 clients)\n")
        for label, s in specs:
            cmd = [
                DEFAULT_PYTHON, CLIENT_SCRIPT,
                "--coord-host", coord_host,
                "--coord-port", str(coord_port),
                "--from-node", s["from_node"],
                "--from-account", s["from_account"],
                "--to-node", s["to_node"],
                "--to-account", s["to_account"],
                "--amount", str(s["amount"]),
            ]
            threading.Thread(target=self._run_client_and_show_result, args=(cmd, label), daemon=True).start()

    def run_conflicting_locks_demo(self):
        try:
            coord_host = self.coord_host_var.get().strip() or DEFAULT_COORDINATOR_HOST
            coord_port = int(self.coord_port_var.get())
        except ValueError:
            messagebox.showerror("Invalid input", "Coordinator port must be an integer")
            return
        # Two concurrent transfers that conflict on B (README demo_conflicting_locks)
        specs = [
            ("C1", {"from_node": "N1", "from_account": "A", "to_node": "N2", "to_account": "B", "amount": 100}),
            ("C2", {"from_node": "N2", "from_account": "B", "to_node": "N3", "to_account": "C", "amount": 150}),
        ]
        self._append_result("Starting conflicting locks demo (2 clients)\n")
        for label, s in specs:
            cmd = [
                DEFAULT_PYTHON, CLIENT_SCRIPT,
                "--coord-host", coord_host,
                "--coord-port", str(coord_port),
                "--from-node", s["from_node"],
                "--from-account", s["from_account"],
                "--to-node", s["to_node"],
                "--to-account", s["to_account"],
                "--amount", str(s["amount"]),
            ]
            threading.Thread(target=self._run_client_and_show_result, args=(cmd, label), daemon=True).start()

    def _run_client_and_show_result(self, cmd: List[str], label: Optional[str] = None):
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True)
            output = completed.stdout.strip()
            error = completed.stderr.strip()
            prefix = f"[{label}] " if label else ""
            if completed.returncode == 0:
                if output:
                    self._append_result(prefix + output + "\n")
                if error:
                    self._append_result(prefix + "WARNINGS:\n" + error + "\n")
            else:
                if error:
                    self._append_result(prefix + "ERROR:\n" + error + "\n")
                if output:
                    self._append_result(prefix + output + "\n")
                self._append_result(prefix + f"Process exited with code {completed.returncode}\n")
        except Exception as e:
            self._append_result((f"[{label}] " if label else "") + f"Execution failed: {e}\n")

    def _append_result(self, text: str):
        def _append():
            self.result_text.insert("end", text)
            self.result_text.see("end")
        self.after(0, _append)

    # Failures / Recovery support
    def _refresh_failures_node_list(self):
        try:
            if hasattr(self, 'fail_node_combo'):
                values = sorted(list(self.nodes.keys())) or ["N1", "N2", "N3"]
                self.fail_node_combo.configure(values=values)
                # keep selection valid
                cur = self.fail_node_var.get()
                if cur not in values and values:
                    self.fail_node_var.set(values[0])
        except Exception:
            pass

    def _build_transfer_cmd_from_fields(self) -> Optional[List[str]]:
        try:
            coord_host = self.coord_host_var.get().strip() or DEFAULT_COORDINATOR_HOST
            coord_port = int(self.coord_port_var.get())
        except ValueError:
            messagebox.showerror("Invalid input", "Coordinator port must be an integer")
            return None
        from_node = self.from_node_var.get().strip()
        from_acc = self.from_account_var.get().strip()
        to_node = self.to_node_var.get().strip()
        to_acc = self.to_account_var.get().strip()
        amount_str = self.amount_var.get().strip()
        if not (from_node and from_acc and to_node and to_acc and amount_str):
            messagebox.showerror("Invalid input", "All transfer fields are required")
            return None
        try:
            amount = int(amount_str)
        except ValueError:
            messagebox.showerror("Invalid input", "Amount must be an integer")
            return None
        cmd = [
            DEFAULT_PYTHON,
            CLIENT_SCRIPT,
            "--coord-host", coord_host,
            "--coord-port", str(coord_port),
            "--from-node", from_node,
            "--from-account", from_acc,
            "--to-node", to_node,
            "--to-account", to_acc,
            "--amount", str(amount),
        ]
        return cmd

    def start_transfer_then_crash_coordinator(self):
        cmd = self._build_transfer_cmd_from_fields()
        if not cmd:
            return
        try:
            delay_ms = int(self.fail_delay_var.get().strip())
        except Exception:
            messagebox.showerror("Invalid delay", "Delay must be an integer (ms)")
            return
        if not self.coordinator or not self.coordinator.is_running():
            messagebox.showerror("Coordinator", "Coordinator is not running")
            return
        self._append_result("Starting transfer, will crash COORDINATOR after delay\n")
        threading.Thread(target=self._scenario_crash_coordinator_task, args=(cmd, delay_ms), daemon=True).start()

    def _scenario_crash_coordinator_task(self, cmd: List[str], delay_ms: int):
        # If a deterministic coordinator failure hook is configured, we don't need to manage timing here.
        fail_at = self.coord_fail_at_var.get().strip() if hasattr(self, 'coord_fail_at_var') else "None"
        use_env_hook = bool(fail_at and fail_at != "None")

        # start transfer
        self._run_client_and_show_result(cmd)

        if use_env_hook:
            # Let the coordinator self-terminate at the selected phase
            self._log("[ui] Coordinator will self-terminate at configured phase (no GUI delay crash).\n")
        else:
            # Fallback to legacy delay-based crash
            time.sleep(max(0, delay_ms) / 1000.0)
            try:
                if self.coordinator and self.coordinator.is_running():
                    self._log("[ui] Injecting failure: terminating coordinator\n")
                    self.coordinator.stop()
                else:
                    self._log("[ui] Coordinator already stopped before crash\n")
            except Exception as e:
                self._log(f"[ui] Error stopping coordinator: {e}\n")
            # restart after ~1.5s
            time.sleep(1.5)
            try:
                if self.coordinator:
                    self.coordinator.start()
                    self._log("[ui] Restarted coordinator after crash\n")
            except Exception as e:
                self._log(f"[ui] Error restarting coordinator: {e}\n")

    def start_transfer_then_crash_node(self):
        cmd = self._build_transfer_cmd_from_fields()
        if not cmd:
            return
        try:
            delay_ms = int(self.fail_delay_var.get().strip())
        except Exception:
            messagebox.showerror("Invalid delay", "Delay must be an integer (ms)")
            return
        node_id = self.fail_node_var.get().strip()
        mp = self.nodes.get(node_id)
        if not mp or not mp.is_running():
            messagebox.showerror("Node", f"Node {node_id} is not running")
            return
        self._append_result(f"Starting transfer, will crash NODE {node_id} after delay\n")
        threading.Thread(target=self._scenario_crash_node_task, args=(cmd, delay_ms, node_id), daemon=True).start()

    def _scenario_crash_node_task(self, cmd: List[str], delay_ms: int, node_id: str):
        mp = self.nodes.get(node_id)
        # start transfer
        self._run_client_and_show_result(cmd)
        # wait then crash node
        time.sleep(max(0, delay_ms) / 1000.0)
        try:
            if mp and mp.is_running():
                self._log(f"[ui] Injecting failure: terminating node {node_id}\n")
                mp.stop()
            else:
                self._log(f"[ui] Node {node_id} already stopped before crash\n")
        except Exception as e:
            self._log(f"[ui] Error stopping node {node_id}: {e}\n")
        # restart after ~1.5s
        time.sleep(1.5)
        try:
            if mp:
                mp.start()
                self._log(f"[ui] Restarted node {node_id} after crash\n")
        except Exception as e:
            self._log(f"[ui] Error restarting node {node_id}: {e}\n")

    def on_close(self):
        try:
            if self.coordinator:
                self.coordinator.stop()
            self.stop_nodes()
        finally:
            self.destroy()


def main():
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
