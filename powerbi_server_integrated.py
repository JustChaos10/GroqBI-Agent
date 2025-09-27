import os
import time
import psutil
from pathlib import Path
import pandas as pd

# =========================
# Robust ADOMD.NET / pyadomd
# =========================
def _import_pyadomd():
    r"""
    Load the ADOMD.NET assembly (x64) before importing pyadomd.
    Supports:
      - ADOMDCLIENT_DLL env var (recommended)
      - C:\\Program Files\\Microsoft.NET\\ADOMD.NET\\<ver>\\Microsoft.AnalysisServices.AdomdClient.dll
      - GAC_MSIL fallback
    """
    dll_candidates = []

    # 1) Env override
    env_dll = os.environ.get("ADOMDCLIENT_DLL")
    if env_dll and Path(env_dll).exists():
        dll_candidates.append(env_dll)

    # 2) Program Files (x64) installs
    root = Path(r"C:\Program Files\Microsoft.NET\ADOMD.NET")
    if root.exists():
        for ver in ("190", "180", "170", "160", "150", "140", "130"):
            p = root / ver / "Microsoft.AnalysisServices.AdomdClient.dll"
            if p.exists():
                dll_candidates.append(str(p))

    # 3) GAC (best-effort)
    gac_root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "assembly" / "GAC_MSIL" / "Microsoft.AnalysisServices.AdomdClient"
    if gac_root.exists():
        for p in gac_root.rglob("Microsoft.AnalysisServices.AdomdClient.dll"):
            dll_candidates.append(str(p))

    # Try to add-reference then import pyadomd
    for dll in dll_candidates:
        try:
            import clr  # pythonnet
            clr.AddReference(dll)
            from pyadomd import Pyadomd
            print(f"✓ ADOMD.NET loaded: {dll}")
            return Pyadomd
        except Exception:
            continue

    # Last resort: plain import (may print a warning banner from pyadomd)
    from pyadomd import Pyadomd
    return Pyadomd


Pyadomd = _import_pyadomd()

from powerbi_agent import PowerBIAgent  # after pyadomd is ready


# ==============
# Helper methods
# ==============
def _workspace_roots():
    r"""
    Candidate roots for AnalysisServicesWorkspaces used by Power BI Desktop.
    - Download edition:
      %LOCALAPPDATA%\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces
      %LOCALAPPDATA%\Microsoft\Power BI Desktop (x64)\AnalysisServicesWorkspaces
    - Store edition:
      %USERPROFILE%\Microsoft\Power BI Desktop Store App\AnalysisServicesWorkspaces
      %LOCALAPPDATA%\Packages\Microsoft.MicrosoftPowerBIDesktop_8wekyb3d8bbwe\LocalState\AnalysisServicesWorkspaces
    """
    la = Path(os.environ.get("LOCALAPPDATA", ""))
    up = Path(os.environ.get("USERPROFILE", ""))

    return [
        la / "Microsoft" / "Power BI Desktop" / "AnalysisServicesWorkspaces",
        la / "Microsoft" / "Power BI Desktop (x64)" / "AnalysisServicesWorkspaces",
        up / "Microsoft" / "Power BI Desktop Store App" / "AnalysisServicesWorkspaces",
        la / "Packages" / "Microsoft.MicrosoftPowerBIDesktop_8wekyb3d8bbwe" / "LocalState" / "AnalysisServicesWorkspaces",
    ]


def _read_port_from_workspace(deadline=None):
    def scan_once():
        candidates = []
        for root in _workspace_roots():
            if root.exists():
                candidates += list(root.glob("*/Data/msmdsrv.port.txt"))

        # newest workspace first
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        for txt in candidates:
            try:
                port = int(txt.read_text().strip())
                if 0 < port < 65536:
                    print(f"✓ Port file: {txt}")
                    return port
            except Exception:
                pass
        return None

    if deadline is None:
        return scan_once()

    while time.time() < deadline:
        p = scan_once()
        if p:
            return p
        time.sleep(1)
    return None


def _find_msmdsrv_child(pbi_proc: psutil.Process):
    try:
        for child in pbi_proc.children(recursive=True):
            if child.name().lower() == "msmdsrv.exe":
                return child
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    return None


def _guess_port_from_pid(ssas_proc: psutil.Process):
    """Fallback: inspect the SSAS TCP listener for a local listening port."""
    try:
        for c in ssas_proc.net_connections(kind="inet"):
            if c.status == psutil.CONN_LISTEN and c.laddr:
                ip = getattr(c.laddr, "ip", None)
                if ip in ("127.0.0.1", "::1", "0.0.0.0", None):
                    return c.laddr.port
    except Exception:
        pass
    return None


# =============
# Main class
# =============
class PowerBIServer:
    """
    Launch Power BI Desktop, detect XMLA port, connect via ADOMD.NET, and run DAX/DMVs.

    Notes:
    - Power BI Desktop hosts a local SSAS instance per session on a RANDOM port;
      the port is written to 'msmdsrv.port.txt' inside the temporary workspace. :contentReference[oaicite:2]{index=2}
    - The TMSCHEMA_* DMVs are **database-scoped**; set **Initial Catalog** to the chosen catalog
      so DMV queries return rows. :contentReference[oaicite:3]{index=3}
    """

    def __init__(self, pbix_path: str, force_new_instance=True,
                 startup_timeout=120, catalog_timeout=240, model_ready_timeout=240):
        self.pbix_path = str(Path(pbix_path).resolve())
        self.force_new_instance = force_new_instance
        self.startup_timeout = startup_timeout
        self.catalog_timeout = catalog_timeout
        self.model_ready_timeout = model_ready_timeout

        self.pbi_proc = None
        self.ssas_proc = None
        self.xmla_port = None
        self.catalog = None

        self.conn = None
        self.agent = PowerBIAgent()

        self._launch_powerbi()
        self._connect_and_select_catalog()
        self._wait_for_model_ready()

    # ---------- Process / port ----------
    def _kill_existing(self):
        if not self.force_new_instance:
            return

        killed = []
        for name in ("PBIDesktop.exe", "msmdsrv.exe"):
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    if p.info["name"] and p.info["name"].lower() == name.lower():
                        proc = psutil.Process(p.pid)
                        proc.terminate()
                        killed.append(proc)
                        print(f"↻ Terminated {name}: PID {p.pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        # Only wait on processes we actually terminated (avoid AccessDenied on unrelated services)
        if killed:
            psutil.wait_procs(killed, timeout=5)

    def _start_pbi(self):
        if not Path(self.pbix_path).exists():
            raise FileNotFoundError(self.pbix_path)

        print(f"▶ Opening PBIX: {self.pbix_path}")
        os.startfile(self.pbix_path)  # returns immediately

        # Find the PBIDesktop process
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            for p in psutil.process_iter(["pid", "name"]):
                if p.info["name"] and p.info["name"].lower() == "pbidesktop.exe":
                    self.pbi_proc = psutil.Process(p.pid)
                    return
            time.sleep(1)
        raise TimeoutError("Timed out starting Power BI Desktop")

    def _detect_ssas_and_port(self):
        # Wait for child msmdsrv
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            proc = _find_msmdsrv_child(self.pbi_proc)
            if proc:
                self.ssas_proc = proc
                print(f"✓ Found SSAS (msmdsrv.exe): PID {proc.pid}")
                break
            time.sleep(1)
        if not self.ssas_proc:
            raise TimeoutError("Could not find msmdsrv.exe under PBIDesktop")

        # Prefer the port file (poll for a while); fallback to socket introspection
        deadline = time.time() + self.startup_timeout
        self.xmla_port = _read_port_from_workspace(deadline=deadline)
        if not self.xmla_port:
            # short fallback window to read the socket
            deadline = time.time() + 15
            while time.time() < deadline and not self.xmla_port:
                self.xmla_port = _guess_port_from_pid(self.ssas_proc)
                if self.xmla_port:
                    break
                time.sleep(1)

        if not self.xmla_port:
            raise TimeoutError("Could not determine XMLA port")
        print(f"✓ XMLA port: {self.xmla_port}")

    def _launch_powerbi(self):
        if self.force_new_instance:
            self._kill_existing()
        self._start_pbi()
        self._detect_ssas_and_port()

    # ---------- Connection / catalog ----------
    def _open_conn(self, initial_catalog: str | None = None):
        # Using MSOLAP provider; set Initial Catalog when we know the database. :contentReference[oaicite:4]{index=4}
        conn_str = f"Provider=MSOLAP;Data Source=localhost:{self.xmla_port};"
        if initial_catalog:
            conn_str += f"Initial Catalog={initial_catalog};"
        self.conn = Pyadomd(conn_str)
        self.conn.open()

    def _first_non_system_catalog(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS")
            cats = [row[0] for row in cur.fetchall()]
        for c in cats:
            if not str(c).startswith("$"):
                return c
        return cats[0] if cats else None

    def _connect_and_select_catalog(self):
        # Step 1: open server-level connection (no Initial Catalog) to list catalogs
        self._open_conn(initial_catalog=None)

        # Step 2: pick first non-system catalog
        cat = self._first_non_system_catalog()
        if not cat:
            raise TimeoutError("No catalogs found on the local SSAS instance.")
        self.catalog = cat
        print(f"✓ Using catalog: {self.catalog}")

        # Step 3: re-open the connection with Initial Catalog so TMSCHEMA_* DMVs return rows
        try:
            if self.conn:
                self.conn.close()
        finally:
            self.conn = None

        self._open_conn(initial_catalog=self.catalog)

    # ---------- Readiness ----------
    def _wait_for_model_ready(self):
        """
        Poll TMSCHEMA_TABLES DMV (db-scoped) until rows appear (confirms model is loaded).
        If it's still warming up, also try DBSCHEMA_TABLES (server rowset) as a sanity check.
        """
        sql_ready = "SELECT * FROM $SYSTEM.TMSCHEMA_TABLES"
        sql_sanity = "SELECT * FROM $SYSTEM.DBSCHEMA_TABLES"

        deadline = time.time() + self.model_ready_timeout

        while time.time() < deadline:
            try:
                # primary: db-scoped DMV
                with self.conn.cursor().execute(sql_ready) as cur:
                    rows = cur.fetchall()
                    if rows:
                        print(f"✓ Model ready; {len(rows)} tables visible in TMSCHEMA_TABLES.")
                        return
            except Exception:
                pass

            # sanity: can we read any server rowset at all?
            try:
                with self.conn.cursor().execute(sql_sanity) as cur:
                    _ = cur.fetchall()
                    # (No need to print; this just confirms connectivity.)
            except Exception:
                pass

            time.sleep(2)

        raise TimeoutError("Model did not become ready in time.")

    # ---------- Public ----------
    def run_dax(self, dax: str) -> pd.DataFrame:
        with self.conn.cursor().execute(dax) as cur:
            cols = [c[0] for c in cur.description]
            data = cur.fetchall()
        return pd.DataFrame(data, columns=cols)

    def close(self):
        try:
            if self.conn:
                self.conn.close()
        finally:
            self.conn = None


def main():
    pbix = os.environ.get("PBIX_FILE", "Store_Sales.pbix")
    server = None
    try:
        server = PowerBIServer(pbix_path=pbix, force_new_instance=True)
        df = server.run_dax('EVALUATE ROW("Test", 1)')
        print(df)
        print("🎉 Connected and querying successfully.")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback; traceback.print_exc()
    finally:
        if server:
            server.close()
            print("✓ Connection closed.")


if __name__ == "__main__":
    main()
