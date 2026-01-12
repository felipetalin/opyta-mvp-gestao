import os
import sys
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from supabase import create_client

# reaproveita as funções do script principal
from import_msproject_xml import import_one_xml  # noqa


def supabase_connect():
    load_dotenv()
    url = os.getenv("SUPABASE_URL")

    # Usa SERVICE ROLE para import/migração
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise RuntimeError("SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não definidos no .env")

    return create_client(url, key)

def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/import_msproject_xml_folder.py <pasta> [--dry-run]")
        sys.exit(1)

    folder = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv

    if not folder.exists() or not folder.is_dir():
        print("ERRO: pasta inválida:", folder)
        sys.exit(1)

    sb = supabase_connect()

    files = sorted(list(folder.glob("*.xml")))
    if not files:
        print("Nenhum .xml encontrado em", folder)
        sys.exit(0)

    ok = 0
    fail = 0
    started = datetime.now()

    for fp in files:
        try:
            print("\n==============================")
            print("IMPORTANDO:", fp.name)
            import_one_xml(sb, str(fp), dry_run=dry_run)
            ok += 1
        except Exception as e:
            fail += 1
            print("FALHOU:", fp.name)
            print("ERRO:", repr(e))

    elapsed = datetime.now() - started
    print("\n==============================")
    print(f"FINALIZADO. OK={ok}  FAIL={fail}  Tempo={elapsed}")


if __name__ == "__main__":
    main()

