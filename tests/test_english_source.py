from __future__ import annotations

"""English-language contract checks for source literals and user-visible copy."""

import ast
import io
import re
import tokenize
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = (ROOT / "telegram_bot", ROOT / "tests")
SOURCE_FILES = (ROOT / "bot.py", ROOT / "ig_scraper.py", ROOT / "uploader.py")
NON_ENGLISH_WORDS = re.compile(
    r"\b(?:"
    r"membuka|ditemukan|gagal|tidak|hanya|anda|kamu|saya|judul|berhasil|hapus|cari|tautan|perintah|pengguna|"
    r"memulai|unggah|unduh|silakan|sedang|tunggu|kapasitas|aturan|melaporkan|kosongkan|cek|lihat|menampilkan|"
    r"memperpendek|konversi|kembali|daftar|fitur|pilih|pilihan|dikirim|lewat|pribadi|buka|ulang|respon|laporan|"
    r"baru|hari|waktu|aktif|selama|semua|lokal|sudah|belum|dengan|untuk|yang|atau|dari|oleh|akan|bisa|masuk|"
    r"keluar|masih|foto|musik|lagu|ikuti|contoh|pakai|terima|kasih|mengirim|mendeteksi|mencari|penuh|langsung|"
    r"kelompok|wajar|jangan|dianggap|terjadi|meneruskan|pesan|menyimpan|sukses|dihapus|nama|tipe|informasi|"
    r"pengaturan|mengambil|menyediakan|meminta|perbarui|perubahan|tersedia|diterima|masalah|sumber|selesai|"
    r"menjalankan|jalankan|mengikuti|memeriksa|memilih|pemilik|kirimkan|alasan|peringatan|masukkan|masukan|"
    r"keterangan|pencarian|tombol|hitung|menambah|menambahkan|terhubung|terputus|mulai|berhenti|berjalan|"
    r"pengembalian|membuat|dibuat|menghapus|mengunduh|mengunggah|mengirimkan|mendukung|didukung|mengubah|"
    r"mengganti|perlu|harus|boleh|dapat|tanpa|setuju|gunakan|menggunakan|berisi|menerima|membalas|balasan|"
    r"lapor|melapor|memberikan|menunjukkan|memperbarui|kendala|durasi|terakhir|sebentar|tekan|digunakan|"
    r"mencapai|batas)\b",
    re.IGNORECASE,
)


class EnglishSourceTests(unittest.TestCase):
    def test_python_source_has_no_non_english_comments_or_literals(self):
        findings = []
        paths = list(SOURCE_FILES)
        for directory in SOURCE_DIRS:
            paths.extend(directory.rglob("*.py"))

        for path in sorted(set(paths)):
            if "__pycache__" in path.parts or path.name == "test_english_source.py":
                continue
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self._check_text(path, node.lineno, "string", node.value, findings)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self._check_text(path, node.lineno, "identifier", node.name, findings)

            for comment in tokenize.generate_tokens(io.StringIO(source).readline):
                if comment.type == tokenize.COMMENT:
                    self._check_text(
                        path, comment.start[0], "comment", comment.string, findings
                    )

        self.assertEqual(findings, [], "Non-English source text found:\n" + "\n".join(findings))

    def _check_text(self, path, line_number, kind, text, findings):
        for match in NON_ENGLISH_WORDS.finditer(text):
            if match.group(0).lower() == "lapor" and path.name != "test_english_source.py":
                if match.group(0) in ("lapor", "LAPOR", "Lapor"):
                    continue
            findings.append(
                f"{path.relative_to(ROOT)}:{line_number}: {kind}: {match.group(0)}"
            )


if __name__ == "__main__":
    unittest.main()
