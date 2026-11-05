"""
Membangun tabel star schema dari data video YouTube MBG.

Input : data/source/videos_clean.csv, data/source/video_per_channel.csv,
        data/source/youtube_labels.csv (hanya label isu video, bukan teks komentar)
Output: data/star/fact_videos.csv, dim_channel.csv, dim_date.csv, dim_province.csv,
        dim_issue.csv, fact_video_issue.csv
        data/star/build_log.json (jumlah baris + hasil pengecekan)

Jalankan dari folder proyek:
    .venv\\Scripts\\python scripts\\build_star_schema.py
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "source"
STAR = ROOT / "data" / "star"

# Label khusus bila video tidak menyebut provinsi, atau menyebut lebih dari satu
PROV_NONE = "(Tidak disebut)"
PROV_MULTI = "(Lebih dari satu)"

# 38 provinsi dan kelompok pulaunya
PROVINSI_PULAU = {
    "Aceh": "Sumatera", "Sumatera Utara": "Sumatera", "Sumatera Barat": "Sumatera",
    "Riau": "Sumatera", "Kepulauan Riau": "Sumatera", "Jambi": "Sumatera",
    "Sumatera Selatan": "Sumatera", "Kepulauan Bangka Belitung": "Sumatera",
    "Bengkulu": "Sumatera", "Lampung": "Sumatera",
    "DKI Jakarta": "Jawa", "Jawa Barat": "Jawa", "Banten": "Jawa", "Jawa Tengah": "Jawa",
    "Daerah Istimewa Yogyakarta": "Jawa", "Jawa Timur": "Jawa",
    "Bali": "Bali dan Nusa Tenggara", "Nusa Tenggara Barat": "Bali dan Nusa Tenggara",
    "Nusa Tenggara Timur": "Bali dan Nusa Tenggara",
    "Kalimantan Barat": "Kalimantan", "Kalimantan Tengah": "Kalimantan",
    "Kalimantan Selatan": "Kalimantan", "Kalimantan Timur": "Kalimantan",
    "Kalimantan Utara": "Kalimantan",
    "Sulawesi Utara": "Sulawesi", "Gorontalo": "Sulawesi", "Sulawesi Tengah": "Sulawesi",
    "Sulawesi Barat": "Sulawesi", "Sulawesi Selatan": "Sulawesi", "Sulawesi Tenggara": "Sulawesi",
    "Maluku": "Maluku", "Maluku Utara": "Maluku",
    "Papua": "Papua", "Papua Barat": "Papua", "Papua Barat Daya": "Papua",
    "Papua Tengah": "Papua", "Papua Pegunungan": "Papua", "Papua Selatan": "Papua",
}

BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
         "Agustus", "September", "Oktober", "November", "Desember"]
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def durasi_ke_detik(iso):
    """Ubah durasi ISO 8601 dari YouTube (mis. PT1H2M3S, P1DT2H) menjadi detik."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", str(iso))
    if not m:
        return None
    d, h, mnt, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mnt * 60 + s


def provinsi_tunggal(teks):
    """Satu provinsi -> nama provinsinya; lebih dari satu atau kosong -> label khusus."""
    if pd.isna(teks) or not str(teks).strip():
        return PROV_NONE
    daftar = [p.strip() for p in str(teks).split(";") if p.strip()]
    return daftar[0] if len(daftar) == 1 else PROV_MULTI


# ---------------------------------------------------------------- baca data
videos = pd.read_csv(SOURCE / "videos_clean.csv")
per_channel = pd.read_csv(SOURCE / "video_per_channel.csv")

published_wib = pd.to_datetime(videos["published_at"], format="ISO8601", utc=True).dt.tz_convert("Asia/Jakarta")

# ---------------------------------------------------------------- fact_videos
# Grain: satu baris = satu video
fact_videos = pd.DataFrame({
    "video_id": videos["video_id"],
    "channel_id": videos["channel_id"],
    "date": published_wib.dt.date,
    "province": videos["province"].map(provinsi_tunggal),
    "title": videos["title"],
    "url": "https://www.youtube.com/watch?v=" + videos["video_id"],
    "view_count": videos["view_count"],
    "like_count": videos["like_count"],
    "comment_count": videos["comment_count"].fillna(0).astype(int),
    "duration_sec": videos["duration"].map(durasi_ke_detik),
    "was_live": videos["was_live"],
})

# ---------------------------------------------------------------- dim_channel
dim_channel = (
    videos[["channel_id", "channel_name", "category"]]
    .drop_duplicates("channel_id")
    .merge(per_channel[["channel_name", "method"]], on="channel_name", how="left")
    .rename(columns={"method": "collection_method"})
    .sort_values("channel_name")
)

# ---------------------------------------------------------------- dim_province
dim_province = pd.DataFrame(
    [(p, pulau) for p, pulau in PROVINSI_PULAU.items()] + [(PROV_MULTI, PROV_MULTI), (PROV_NONE, PROV_NONE)],
    columns=["province", "island_group"],
)

# ---------------------------------------------------------------- dim_date
# Satu baris per tanggal, tanpa bolong, dari tanggal video pertama sampai terakhir
tanggal = pd.date_range(fact_videos["date"].min(), fact_videos["date"].max(), freq="D")
dim_date = pd.DataFrame({
    "date": tanggal.date,
    "year": tanggal.year,
    "quarter": "Q" + tanggal.quarter.astype(str),
    "month_number": tanggal.month,
    "month_name": [BULAN[m - 1] for m in tanggal.month],
    "year_month": tanggal.strftime("%Y-%m"),
    "day_of_week_number": tanggal.day_of_week + 1,  # 1 = Senin
    "day_name": [HARI[d] for d in tanggal.day_of_week],
})

# ---------------------------------------------------------------- dim_issue
# 7 kategori isu keamanan pangan (urutan = urutan tampil di Power BI)
ISU = [
    ("keracunan", "Keracunan"),
    ("gejala_kesehatan", "Gejala Kesehatan"),
    ("higiene_sanitasi", "Higiene & Sanitasi"),
    ("basi_busuk", "Basi / Busuk"),
    ("benda_asing", "Benda Asing"),
    ("kontaminasi_bakteri", "Kontaminasi Bakteri"),
    ("kualitas_matang", "Kualitas Kematangan"),
]
dim_issue = pd.DataFrame(
    [(kode, label, i + 1) for i, (kode, label) in enumerate(ISU)],
    columns=["issue", "issue_label", "issue_order"],
)

# ---------------------------------------------------------------- fact_video_issue
# Grain: satu baris = satu video x satu isu (video bisa punya beberapa isu).
# Kolom channel_id, date, province ikut disalin supaya tabel ini bisa langsung
# berelasi ke dimension yang sama (conformed dimension), tanpa relasi dua arah.
labels = pd.read_csv(SOURCE / "youtube_labels.csv", usecols=["doc_id", "rq1_issue_categories"])
labels = labels[labels["doc_id"].str.startswith("yt_v_") & labels["rq1_issue_categories"].notna()]
labels["video_id"] = labels["doc_id"].str.removeprefix("yt_v_")
labels["issue"] = labels["rq1_issue_categories"].str.split(";")
fact_video_issue = (
    labels.explode("issue")[["video_id", "issue"]]
    .assign(issue=lambda d: d["issue"].str.strip())
    .drop_duplicates()
    .merge(fact_videos[["video_id", "channel_id", "date", "province"]], on="video_id", how="inner")
    .sort_values(["date", "video_id", "issue"])
)

# ---------------------------------------------------------------- pengecekan
# Kunci di dimension harus unik, dan setiap kunci di fact harus ada di dimension
checks = {
    "video_id unik": fact_videos["video_id"].is_unique,
    "channel_id unik di dim_channel": dim_channel["channel_id"].is_unique,
    "province unik di dim_province": dim_province["province"].is_unique,
    "date unik di dim_date": dim_date["date"].is_unique,
    "semua channel_id fact ada di dim_channel": fact_videos["channel_id"].isin(dim_channel["channel_id"]).all(),
    "semua province fact ada di dim_province": fact_videos["province"].isin(dim_province["province"]).all(),
    "semua date fact ada di dim_date": fact_videos["date"].isin(dim_date["date"]).all(),
    "semua durasi terbaca": fact_videos["duration_sec"].notna().all(),
    "issue unik di dim_issue": dim_issue["issue"].is_unique,
    "semua issue fact ada di dim_issue": fact_video_issue["issue"].isin(dim_issue["issue"]).all(),
    "pasangan video x isu unik": not fact_video_issue.duplicated(["video_id", "issue"]).any(),
    "semua label video cocok dengan fact_videos": labels["video_id"].isin(fact_videos["video_id"]).all(),
}
for nama, lolos in checks.items():
    print(("PASS" if lolos else "FAIL"), "-", nama)

# ---------------------------------------------------------------- simpan
STAR.mkdir(parents=True, exist_ok=True)
tables = {
    "fact_videos": fact_videos,
    "dim_channel": dim_channel,
    "dim_date": dim_date,
    "dim_province": dim_province,
    "dim_issue": dim_issue,
    "fact_video_issue": fact_video_issue,
}
for nama, df in tables.items():
    df.to_csv(STAR / f"{nama}.csv", index=False, encoding="utf-8")
    print(f"{nama}: {len(df):,} baris -> data/star/{nama}.csv")

log = {
    "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "rows": {nama: len(df) for nama, df in tables.items()},
    "checks": {nama: bool(lolos) for nama, lolos in checks.items()},
    "all_pass": all(checks.values()),
}
(STAR / "build_log.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")

if not log["all_pass"]:
    raise SystemExit("Ada pengecekan yang FAIL, lihat data/star/build_log.json")
