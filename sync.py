import os
import sys
import psycopg2
from psycopg2.extras import execute_values


# ==========================================
# 1. AMBIL CONNECTION STRING DARI GITHUB SECRETS
# ==========================================

KONEKSI_KABUPATEN = {
    "KARO": os.environ.get("DB_KARO"),
    "DELI SERDANG": os.environ.get("DB_DELI"),
    "LANGKAT": os.environ.get("DB_LANGKAT"),
}
DB_PUSAT = os.environ.get("DB_PUSAT")

kosong = [nama for nama, url in KONEKSI_KABUPATEN.items() if not url]
if not DB_PUSAT:
    kosong.append("PUSAT")

if kosong:
    print("ERROR: Secret belum diisi untuk:", ", ".join(kosong))
    sys.exit(1)


def buka_koneksi(url):
    return psycopg2.connect(url, sslmode="require", connect_timeout=20)


# ==========================================
# 2. PASTIKAN TABEL PUSAT ADA
# ==========================================

SQL_BUAT_TABEL_PUSAT = """
CREATE TABLE IF NOT EXISTS petani_pusat (
    kode_petani VARCHAR(20) PRIMARY KEY,
    nama_petani VARCHAR(100) NOT NULL,
    desa VARCHAR(100) NOT NULL,
    komoditas VARCHAR(100) NOT NULL,
    luas_lahan NUMERIC(8,2) NOT NULL,
    wilayah_sumber VARCHAR(50) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


# ==========================================
# 3. BACA DATA DARI SETIAP KABUPATEN
# ==========================================

def ambil_data_kabupaten(wilayah, url):
    conn = buka_koneksi(url)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT kode_petani, nama_petani, desa,
                       komoditas, luas_lahan, updated_at
                FROM petani
            """)
            rows = cur.fetchall()
        print(f"{wilayah}: {len(rows)} baris dibaca")
        return [
            (r[0], r[1], r[2], r[3], r[4], wilayah, r[5])
            for r in rows
        ]
    finally:
        conn.close()


# ==========================================
# 4. KIRIM KE DATABASE PUSAT (UPSERT)
# ==========================================

SQL_UPSERT_PUSAT = """
INSERT INTO petani_pusat (
    kode_petani, nama_petani, desa, komoditas,
    luas_lahan, wilayah_sumber, updated_at
)
VALUES %s
ON CONFLICT (kode_petani)
DO UPDATE SET
    nama_petani = EXCLUDED.nama_petani,
    desa = EXCLUDED.desa,
    komoditas = EXCLUDED.komoditas,
    luas_lahan = EXCLUDED.luas_lahan,
    wilayah_sumber = EXCLUDED.wilayah_sumber,
    updated_at = EXCLUDED.updated_at;
"""


def main():
    print("=== SINKRONISASI SIM-PETANI DIMULAI ===")

    semua_data = []
    for wilayah, url in KONEKSI_KABUPATEN.items():
        semua_data.extend(ambil_data_kabupaten(wilayah, url))

    kode = [row[0] for row in semua_data]
    if len(kode) != len(set(kode)):
        print("ERROR: Ada kode_petani duplikat antar kabupaten.")
        sys.exit(1)

    if not semua_data:
        print("Tidak ada data untuk disinkronkan.")
        return

    conn = buka_koneksi(DB_PUSAT)
    try:
        with conn.cursor() as cur:
            cur.execute(SQL_BUAT_TABEL_PUSAT)
            execute_values(cur, SQL_UPSERT_PUSAT, semua_data)

            cur.execute("""
                SELECT wilayah_sumber, COUNT(*)
                FROM petani_pusat
                GROUP BY wilayah_sumber
                ORDER BY wilayah_sumber
            """)
            ringkasan = cur.fetchall()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"BERHASIL: {len(semua_data)} baris disinkronkan ke pusat")
    for wilayah, jumlah in ringkasan:
        print(f"  - {wilayah}: {jumlah} baris")
    print("=== SINKRONISASI SELESAI ===")


if __name__ == "__main__":
    main()
