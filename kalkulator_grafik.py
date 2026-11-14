# -*- coding: utf-8 -*-
"""
Kalkulator Grafik — aplikasi menggambar kurva persamaan matematika (ala Desmos).
Satu berkas Python murni (hanya pustaka standar + Tkinter; Pillow opsional
untuk ekspor PNG). Ditulis agar bisa dibungkus PyInstaller menjadi .exe Windows.

Fitur:
- Banyak fungsi sekaligus, tiap fungsi berwarna sendiri.
- Parser rumus aman (tanpa eval): ^ pangkat, akar, sin/cos/tan, log, ln, |x|,
  perkalian implisit (2x, 3(x+1), xy), koma desimal ala Indonesia (0,5).
- Slider parameter otomatis: huruf selain x (a, b, c, ...) menjadi penggeser.
- Titik koordinat dicari sendiri: tabel titik, titik potong sumbu X/Y,
  titik potong antar kurva — semuanya juga tersedia sebagai teks.
- Kurva turunan f'(x), zoom & geser bidang, simpan grafik sebagai PNG.
"""

import math
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageDraw
    PUNYA_PIL = True
except Exception:
    PUNYA_PIL = False

# ======================================================================
# BAGIAN 1 — PARSER RUMUS (aman, tanpa eval)
# ======================================================================

FUNGSI = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "sqrt": math.sqrt, "exp": math.exp,
    "log": math.log10,          # log = basis 10 (kebiasaan sekolah di Indonesia)
    "ln": math.log,             # ln  = logaritma natural
    "abs": abs,
}
KONSTAN = {"pi": math.pi, "tau": math.tau, "e": math.e}
# nama-nama yang dikenali utuh (diurutkan dari yang terpanjang)
_NAMA_DIKENAL = sorted(list(FUNGSI) + list(KONSTAN), key=len, reverse=True)


class GalatRumus(Exception):
    pass


def _tokenisasi(teks):
    """Ubah teks rumus menjadi daftar token. Mendukung perkalian implisit:
    nama yang tidak dikenal dipecah per huruf (xy -> x * y)."""
    teks = teks.replace(" ", "").replace("**", "^").replace("√(", "sqrt(")
    teks = teks.replace(",", ".")  # koma desimal Indonesia: 0,5 -> 0.5
    token = []
    i, n = 0, len(teks)
    while i < n:
        c = teks[i]
        if c.isdigit() or (c == "." and i + 1 < n and teks[i + 1].isdigit()):
            j = i
            while j < n and (teks[j].isdigit() or teks[j] == "."):
                j += 1
            try:
                token.append(("num", float(teks[i:j])))
            except ValueError:
                raise GalatRumus("Angka tidak valid: " + teks[i:j])
            i = j
        elif c.isalpha():
            cocok = None
            for nama in _NAMA_DIKENAL:
                if teks.startswith(nama, i):
                    cocok = nama
                    break
            if cocok:
                token.append(("nama", cocok))
                i += len(cocok)
            else:
                token.append(("nama", c))  # satu huruf = satu variabel
                i += 1
        elif c in "+-*/^":
            token.append(("op", c))
            i += 1
        elif c == "(":
            token.append(("(", c))
            i += 1
        elif c == ")":
            token.append((")", c))
            i += 1
        elif c == "|":
            token.append(("|", c))
            i += 1
        else:
            raise GalatRumus("Karakter tidak dikenal: " + repr(c))
    # sisipkan '*' untuk perkalian implisit: 2x, 3(, )x, )(
    hasil = []
    for tok in token:
        if hasil:
            kiri, kanan = hasil[-1], tok
            kiri_tutup = kiri[0] in ("num", ")") or (
                kiri[0] == "nama" and kiri[1] not in FUNGSI)
            kanan_buka = kanan[0] in ("num", "(") or kanan[0] == "nama"
            if kiri_tutup and kanan_buka:
                hasil.append(("op", "*"))
        hasil.append(tok)
    return hasil


class _Parser:
    def __init__(self, token):
        self.t = token
        self.i = 0

    def _intip(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def _ambil(self):
        tok = self._intip()
        self.i += 1
        return tok

    def parse(self):
        if not self.t:
            raise GalatRumus("Rumus kosong")
        pohon = self._ekspresi()
        if self.i != len(self.t):
            raise GalatRumus("Ada sisa teks rumus yang tidak terbaca")
        return pohon

    def _ekspresi(self):
        node = self._suku()
        while self._intip() == ("op", "+") or self._intip() == ("op", "-"):
            op = self._ambil()[1]
            node = ("bin", op, node, self._suku())
        return node

    def _suku(self):
        node = self._unary()
        while self._intip() == ("op", "*") or self._intip() == ("op", "/"):
            op = self._ambil()[1]
            node = ("bin", op, node, self._unary())
        return node

    def _unary(self):
        if self._intip() == ("op", "-"):
            self._ambil()
            return ("neg", self._unary())
        if self._intip() == ("op", "+"):
            self._ambil()
            return self._unary()
        return self._pangkat()

    def _pangkat(self):
        node = self._primer()
        if self._intip() == ("op", "^"):
            self._ambil()
            node = ("bin", "^", node, self._unary())  # asosiatif kanan
        return node

    def _primer(self):
        jenis, nilai = self._ambil()
        if jenis == "num":
            return ("num", nilai)
        if jenis == "(":
            node = self._ekspresi()
            if self._ambil() != (")", ")"):
                raise GalatRumus("Kurung tutup hilang")
            return node
        if jenis == "|":
            node = self._ekspresi()
            if self._ambil() != ("|", "|"):
                raise GalatRumus("Tanda | penutup nilai mutlak hilang")
            return ("call", "abs", node)
        if jenis == "nama":
            if nilai in FUNGSI:
                if self._ambil() != ("(", "("):
                    raise GalatRumus("Fungsi " + nilai + " harus diikuti ( ... )")
                arg = self._ekspresi()
                if self._ambil() != (")", ")"):
                    raise GalatRumus("Kurung tutup hilang setelah " + nilai)
                return ("call", nilai, arg)
            if nilai in KONSTAN:
                return ("num", KONSTAN[nilai])
            return ("var", nilai)
        raise GalatRumus("Rumus tidak lengkap atau salah tulis")


def urai_rumus(teks):
    """Teks rumus -> pohon sintaks. Melempar GalatRumus bila salah tulis."""
    t = teks.strip()
    padat = t.replace(" ", "")
    if padat.lower().startswith("y="):
        t = padat[2:]
    return _Parser(_tokenisasi(t)).parse()


def variabel_bebas(pohon):
    """Semua variabel selain x yang dipakai rumus (jadi parameter slider)."""
    ketemu = set()

    def jalan(node):
        if node[0] == "var":
            if node[1] != "x":
                ketemu.add(node[1])
        elif node[0] == "neg":
            jalan(node[1])
        elif node[0] == "bin":
            jalan(node[2])
            jalan(node[3])
        elif node[0] == "call":
            jalan(node[2])

    jalan(pohon)
    return ketemu


def nilai(pohon, env):
    """Hitung nilai pohon sintaks dengan env = {'x': ..., 'a': ..., ...}."""
    jenis = pohon[0]
    if jenis == "num":
        return pohon[1]
    if jenis == "var":
        return env[pohon[1]]
    if jenis == "neg":
        return -nilai(pohon[1], env)
    if jenis == "call":
        return FUNGSI[pohon[1]](nilai(pohon[2], env))
    # bin
    op, a, b = pohon[1], nilai(pohon[2], env), nilai(pohon[3], env)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return a / b
    if op == "^":
        if a < 0 and b != int(b):
            raise ValueError("pangkat pecahan dari bilangan negatif")
        return a ** b
    raise GalatRumus("Operator tidak dikenal: " + op)


def nilai_aman(pohon, env):
    """Seperti nilai(), tapi kegagalan hitung -> NaN (aman untuk menggambar)."""
    try:
        v = nilai(pohon, env)
        if isinstance(v, complex):
            return math.nan
        return float(v)
    except Exception:
        return math.nan


# ======================================================================
# BAGIAN 2 — PENCARI TITIK (akar, titik potong) SECARA NUMERIK
# ======================================================================

def _biseksi(f, a, b, fa):
    for _ in range(60):
        m = 0.5 * (a + b)
        fm = f(m)
        if math.isnan(fm):
            return None
        if fa * fm <= 0:
            b = m
        else:
            a, fa = m, fm
    return 0.5 * (a + b)


def cari_akar(f, x0, x1, contoh=2400, maks=20):
    """Cari semua x di [x0, x1] dengan f(x) = 0 (titik potong sumbu X)."""
    akar = []
    langkah = (x1 - x0) / contoh
    xa, fa = x0, f(x0)
    for i in range(1, contoh + 1):
        xb = x0 + i * langkah
        fb = f(xb)
        if not math.isnan(fa) and not math.isnan(fb):
            if fb == 0.0:
                akar.append(xb)
            elif fa * fb < 0:
                r = _biseksi(f, xa, xb, fa)
                if r is not None:
                    akar.append(r)
        xa, fa = xb, fb
    bersih = []
    for r in akar:
        if all(abs(r - s) > 1e-4 for s in bersih):
            bersih.append(r)
        if len(bersih) >= maks:
            break
    return bersih


def turunan_angka(f, x):
    """Turunan numerik f di titik x (selisih pusat)."""
    h = 1e-4 * max(1.0, abs(x))
    a, b = f(x - h), f(x + h)
    if math.isnan(a) or math.isnan(b):
        return math.nan
    return (b - a) / (2 * h)


def fmt(angka, desimal=4):
    """Format angka ringkas: buang nol berlebih, koma desimal Indonesia."""
    if angka is None or (isinstance(angka, float) and (math.isnan(angka) or math.isinf(angka))):
        return "-"
    s = ("%.*f" % (desimal, angka)).rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s.replace(".", ",")


# ======================================================================
# BAGIAN 3 — ANTARMUKA (Tkinter)
# ======================================================================

WARNA_KURVA = ["#22d3ee", "#fbbf24", "#f472b6", "#4ade80",
               "#a78bfa", "#f87171", "#38bdf8", "#facc15"]
BG = "#0b1220"
PANEL = "#101a2e"
PANEL2 = "#0d1526"
TEKS = "#e5edf7"
TEKS_LEMBUT = "#8fa3bf"
GRID_HALUS = "#1b2a45"
GRID_SUMBU = "#54749e"
AKSEN = "#22d3ee"


class BarisFungsi:
    """Satu baris rumus di panel kiri."""

    def __init__(self, app, induk, warna):
        self.app = app
        self.warna = warna
        self.poohon = None          # pohon sintaks hasil urai (None = belum)
        self.galat = ""
        bingkai = tk.Frame(induk, bg=PANEL)
        bingkai.pack(fill="x", padx=6, pady=3)
        self.titik_warna = tk.Button(
            bingkai, text="●", fg=warna, bg=PANEL, bd=0, font=("Segoe UI", 13),
            activebackground=PANEL, command=self._putar_warna)
        self.titik_warna.pack(side="left")
        self.var_teks = tk.StringVar()
        self.entri = tk.Entry(
            bingkai, textvariable=self.var_teks, bg="#0a1120", fg=TEKS,
            insertbackground=TEKS, relief="flat", font=("Consolas", 11))
        self.entri.pack(side="left", fill="x", expand=True, padx=4, ipady=3)
        self.entri.bind("<KeyRelease>", lambda e: app.jadwal_gambar())
        self.entri.bind("<FocusIn>", lambda e: app.pilih_baris(self))
        self.var_tampil = tk.BooleanVar(value=True)
        tk.Checkbutton(bingkai, variable=self.var_tampil, bg=PANEL,
                       activebackground=PANEL, selectcolor=PANEL2,
                       command=app.gambar).pack(side="left")
        self.var_turunan = tk.BooleanVar(value=False)
        self.btn_turunan = tk.Button(
            bingkai, text="f′", fg=TEKS_LEMBUT, bg=PANEL, bd=0,
            activebackground=PANEL, font=("Segoe UI", 10, "bold"),
            command=self._alih_turunan)
        self.btn_turunan.pack(side="left")
        tk.Button(bingkai, text="✕", fg=TEKS_LEMBUT, bg=PANEL, bd=0,
                  activebackground=PANEL,
                  command=lambda: app.hapus_baris(self)).pack(side="left")
        self.bingkai = bingkai

    def _alih_turunan(self):
        self.var_turunan.set(not self.var_turunan.get())
        self.btn_turunan.config(
            fg="#22d3ee" if self.var_turunan.get() else "#8fa3bf")
        self.app.gambar()

    def _putar_warna(self):
        i = WARNA_KURVA.index(self.warna)
        self.warna = WARNA_KURVA[(i + 1) % len(WARNA_KURVA)]
        self.titik_warna.config(fg=self.warna)
        self.app.gambar()

    def teks(self):
        return self.var_teks.get().strip()

    def urai(self):
        """Urai teks rumus baris ini; simpan pohon/galat."""
        t = self.teks()
        if not t:
            self.poohon, self.galat = None, ""
            self.entri.config(bg="#0a1120")
            return
        try:
            self.poohon, self.galat = urai_rumus(t), ""
            self.entri.config(bg="#0a1120")
        except GalatRumus as e:
            self.poohon, self.galat = None, str(e)
            self.entri.config(bg="#3a1220")


class Aplikasi(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Kalkulator Grafik")
        self.geometry("1240x780")
        self.configure(bg=BG)
        # keadaan bidang gambar (koordinat matematika <-> piksel)
        self.skala = 45.0            # piksel per 1 satuan
        self.ox = 0.0                # posisi piksel titik (0,0); diisi saat gambar
        self.oy = 0.0
        self.baris = []              # daftar BarisFungsi
        self.baris_aktif = None
        self.param = {}              # nama -> DoubleVar slider
        self._param_dicetak = None   # himpunan parameter yang slidernya tampil
        self._jadwal = None
        self._seret = None
        self._ikut_tengah = True     # titik (0,0) tetap di tengah sampai digeser
        self._bangun_ui()
        self.isi_contoh("parabola")
        self.gambar()

    # ---------- bangun tampilan ----------
    def _bangun_ui(self):
        kepala = tk.Frame(self, bg=PANEL)
        kepala.pack(fill="x")
        tk.Label(kepala, text="Kalkulator Grafik", bg=PANEL, fg=TEKS,
                 font=("Segoe UI", 16, "bold")).pack(side="left", padx=12, pady=8)
        tk.Label(kepala, text="Ketik rumus, kurvanya menggambar sendiri — "
                              "titik koordinat dicari otomatis.",
                 bg=PANEL, fg=TEKS_LEMBUT,
                 font=("Segoe UI", 10)).pack(side="left")

        badan = tk.Frame(self, bg=BG)
        badan.pack(fill="both", expand=True)

        kiri = tk.Frame(badan, bg=PANEL, width=400)
        kiri.pack(side="left", fill="y")
        kiri.pack_propagate(False)

        tk.Label(kiri, text="Daftar Fungsi  (y = ...)", bg=PANEL, fg=TEKS,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10, pady=(10, 2))
        self.wadah_baris = tk.Frame(kiri, bg=PANEL)
        self.wadah_baris.pack(fill="x")
        tk.Button(kiri, text="＋  Tambah Fungsi", bg="#16263f", fg=TEKS, bd=0,
                  activebackground="#1d3252", font=("Segoe UI", 10),
                  command=self.tambah_baris).pack(fill="x", padx=10, pady=4, ipady=3)

        tk.Label(kiri, text="Parameter (slider)", bg=PANEL, fg=TEKS,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10, pady=(12, 2))
        self.wadah_param = tk.Frame(kiri, bg=PANEL)
        self.wadah_param.pack(fill="x")
        self.label_param_kosong = tk.Label(
            self.wadah_param, text="Belum ada parameter. Coba rumus a*x + b.",
            bg=PANEL, fg=TEKS_LEMBUT, font=("Segoe UI", 9))
        self.label_param_kosong.pack(anchor="w", padx=10)
        self.wadah_slider = tk.Frame(self.wadah_param, bg=PANEL)
        self.wadah_slider.pack(fill="x")

        tk.Label(kiri, text="Titik & Analisis", bg=PANEL, fg=TEKS,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10, pady=(12, 2))
        self.teks_analisis = tk.Text(
            kiri, bg="#0a1120", fg=TEKS, relief="flat", height=14,
            font=("Consolas", 9), wrap="word")
        self.teks_analisis.pack(fill="both", expand=True, padx=10, pady=2)
        tk.Button(kiri, text="Salin Teks Analisis", bg="#16263f", fg=TEKS, bd=0,
                  activebackground="#1d3252", font=("Segoe UI", 9),
                  command=self._salin_analisis).pack(fill="x", padx=10, pady=6, ipady=2)

        kanan = tk.Frame(badan, bg=BG)
        kanan.pack(side="left", fill="both", expand=True)
        alat = tk.Frame(kanan, bg=BG)
        alat.pack(fill="x", padx=8, pady=6)
        for teks_btn, perintah in (("Perkecil", lambda: self.zoom(0.8)),
                                   ("Perbesar", lambda: self.zoom(1.25)),
                                   ("Atur Ulang", self.atur_ulang)):
            tk.Button(alat, text=teks_btn, bg="#16263f", fg=TEKS, bd=0,
                      activebackground="#1d3252", font=("Segoe UI", 10),
                      command=perintah).pack(side="left", padx=3, ipadx=6, ipady=3)
        tk.Button(alat, text="Simpan PNG", bg="#16263f", fg=TEKS, bd=0,
                  activebackground="#1d3252", font=("Segoe UI", 10),
                  command=self.simpan_png).pack(side="left", padx=3, ipadx=6, ipady=3)
        mb = tk.Menubutton(alat, text="Contoh Rumus  ▾", bg="#16263f", fg=TEKS,
                           bd=0, activebackground="#1d3252", font=("Segoe UI", 10))
        menu = tk.Menu(mb, tearoff=0, bg=PANEL, fg=TEKS)
        for kunci, label in (("parabola", "Parabola & garis"),
                             ("gelombang", "Gelombang sin & cos"),
                             ("slider", "Garis dengan slider a, b"),
                             ("kubik", "Kurva pangkat tiga"),
                             ("ekspolog", "Eksponen & logaritma")):
            menu.add_command(label=label,
                             command=lambda k=kunci: self.isi_contoh(k))
        mb.config(menu=menu)
        mb.pack(side="left", padx=3, ipadx=6, ipady=3)

        self.kanvas = tk.Canvas(kanan, bg="#0a1120", highlightthickness=0)
        self.kanvas.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        self.kanvas.bind("<Configure>", lambda e: self.gambar())
        self.kanvas.bind("<Motion>", self._gerak_mouse)
        self.kanvas.bind("<ButtonPress-1>", self._mulai_seret)
        self.kanvas.bind("<B1-Motion>", self._seret_mouse)
        self.kanvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "_seret", None))
        self.kanvas.bind("<MouseWheel>", self._roda_mouse)      # Windows/macOS
        self.kanvas.bind("<Button-4>", lambda e: self.zoom(1.15))  # Linux
        self.kanvas.bind("<Button-5>", lambda e: self.zoom(0.87))  # Linux

        self.status = tk.Label(self, text="", bg=PANEL, fg=TEKS_LEMBUT,
                               anchor="w", font=("Segoe UI", 9))
        self.status.pack(fill="x", padx=0, pady=0, ipadx=10, ipady=3)

    # ---------- baris fungsi & parameter ----------
    def tambah_baris(self, teks_awal=""):
        warna = WARNA_KURVA[len(self.baris) % len(WARNA_KURVA)]
        b = BarisFungsi(self, self.wadah_baris, warna)
        if teks_awal:
            b.var_teks.set(teks_awal)
        self.baris.append(b)
        if self.baris_aktif is None:
            self.baris_aktif = b
        return b

    def hapus_baris(self, b):
        if len(self.baris) <= 1:
            b.var_teks.set("")
        else:
            self.baris.remove(b)
            b.bingkai.destroy()
            if self.baris_aktif is b:
                self.baris_aktif = self.baris[0] if self.baris else None
        self.gambar()

    def pilih_baris(self, b):
        self.baris_aktif = b
        self.gambar()

    def isi_contoh(self, kunci):
        contoh = {
            "parabola": ["x^2 - 3x + 2", "2x + 1"],
            "gelombang": ["sin(x)", "cos(x)"],
            "slider": ["a*x + b"],
            "kubik": ["x^3 - 3x"],
            "ekspolog": ["2^x", "log(x)"],
        }[kunci]
        for b in list(self.baris):
            b.bingkai.destroy()
        self.baris.clear()
        for t in contoh:
            self.tambah_baris(t)
        self.atur_ulang(tanpa_gambar=True)
        self.gambar()

    def _sinkron_param(self):
        """Buat/hapus slider mengikuti parameter yang dipakai semua rumus."""
        perlu = set()
        for b in self.baris:
            if b.poohon is not None:
                perlu |= variabel_bebas(b.poohon)
        if perlu == self._param_dicetak:
            return  # himpunan parameter sama: jangan bangun ulang slider
        self._param_dicetak = set(perlu)
        for nama in list(self.param):
            if nama not in perlu:
                del self.param[nama]
        for nama in sorted(perlu):
            if nama not in self.param:
                awal = 0.0 if nama in ("b", "c", "d") else 1.0
                self.param[nama] = tk.DoubleVar(value=awal)
        for anak in self.wadah_slider.winfo_children():
            anak.destroy()
        self.label_param_kosong.pack_forget()
        if not perlu:
            self.label_param_kosong.pack(anchor="w", padx=10)
            return
        for nama in sorted(perlu):
            bingkai = tk.Frame(self.wadah_slider, bg=PANEL)
            bingkai.pack(fill="x", padx=10, pady=1)
            tk.Label(bingkai, text=nama, bg=PANEL, fg=AKSEN, width=2,
                     font=("Segoe UI", 11, "bold")).pack(side="left")
            lab = tk.Label(bingkai, text=fmt(self.param[nama].get(), 2),
                           bg=PANEL, fg=TEKS, width=6, font=("Consolas", 10))
            lab.pack(side="right")
            geser = tk.Scale(
                bingkai, variable=self.param[nama], from_=-10, to=10,
                resolution=0.05, orient="horizontal", showvalue=False,
                bg=PANEL, fg=TEKS, troughcolor="#0a1120", highlightthickness=0,
                activebackground=AKSEN, length=230,
                command=lambda v, l=lab: (l.config(text=fmt(float(v), 2)),
                                          self.gambar()))
            geser.pack(side="left", fill="x", expand=True)

    def _env(self, x):
        env = {"x": x}
        for nama, var in self.param.items():
            env[nama] = var.get()
        return env

    # ---------- gambar ----------
    def jadwal_gambar(self):
        if self._jadwal:
            self.after_cancel(self._jadwal)
        self._jadwal = self.after(160, self.gambar)

    def gambar(self):
        self._jadwal = None
        for b in self.baris:
            b.urai()
        self._sinkron_param()
        lebar = max(self.kanvas.winfo_width(), 50)
        tinggi = max(self.kanvas.winfo_height(), 50)
        if self._ikut_tengah:
            self.ox, self.oy = lebar / 2, tinggi / 2
        c = self.kanvas
        c.delete("all")
        self._gambar_grid(lebar, tinggi)
        aktif = [b for b in self.baris
                 if b.poohon is not None and b.var_tampil.get()]
        for b in aktif:
            self._plot(b, lebar, tinggi)
            if b.var_turunan.get():
                self._plot(b, lebar, tinggi, turunan=True)
        self._tandai_titik(aktif, lebar, tinggi)
        self._isi_analisis(aktif, lebar)
        galat = [b.galat for b in self.baris if b.galat]
        if galat:
            self.status.config(text="Rumus bermasalah: " + galat[0])
        elif not aktif:
            self.status.config(
                text="Ketik rumus di panel kiri, contoh: x^2 - 3x + 2")

    def _ke_layar(self, x, y):
        return self.ox + x * self.skala, self.oy - y * self.skala

    def _ke_dunia(self, px, py):
        return (px - self.ox) / self.skala, (self.oy - py) / self.skala

    def _gambar_grid(self, lebar, tinggi):
        c = self.kanvas
        x0, _ = self._ke_dunia(0, 0)
        x1, _ = self._ke_dunia(lebar, 0)
        _, y1 = self._ke_dunia(0, 0)
        _, y0 = self._ke_dunia(0, tinggi)
        for gx in range(math.floor(x0), math.ceil(x1) + 1):
            px, _ = self._ke_layar(gx, 0)
            c.create_line(px, 0, px, tinggi, fill=GRID_HALUS)
            if gx != 0:
                c.create_text(px + 3, self.oy + 4, text=str(gx), anchor="nw",
                              fill=TEKS_LEMBUT, font=("Segoe UI", 8))
        for gy in range(math.floor(y0), math.ceil(y1) + 1):
            _, py = self._ke_layar(0, gy)
            c.create_line(0, py, lebar, py, fill=GRID_HALUS)
            if gy != 0:
                c.create_text(self.ox + 4, py - 2, text=str(gy), anchor="w",
                              fill=TEKS_LEMBUT, font=("Segoe UI", 8))
        c.create_line(0, self.oy, lebar, self.oy, fill=GRID_SUMBU, width=2)
        c.create_line(self.ox, 0, self.ox, tinggi, fill=GRID_SUMBU, width=2)
        c.create_text(lebar - 8, self.oy - 8, text="x", anchor="e",
                      fill=TEKS, font=("Segoe UI", 11, "bold"))
        c.create_text(self.ox + 8, 8, text="y", anchor="w",
                      fill=TEKS, font=("Segoe UI", 11, "bold"))

    def _plot(self, b, lebar, tinggi, turunan=False):
        c = self.kanvas
        f = lambda x: nilai_aman(b.poohon, self._env(x))
        if turunan:
            g = lambda x: turunan_angka(f, x)
        else:
            g = f
        segmen = []
        for px in range(0, lebar + 1, 2):
            wx, _ = self._ke_dunia(px, 0)
            wy = g(wx)
            if math.isnan(wy) or math.isinf(wy):
                if len(segmen) > 1:
                    self._gambar_segmen(segmen, b.warna, turunan)
                segmen = []
                continue
            _, py = self._ke_layar(0, wy)
            if segmen and abs(py - segmen[-1][1]) > tinggi * 1.5:
                if len(segmen) > 1:
                    self._gambar_segmen(segmen, b.warna, turunan)
                segmen = []
            segmen.append((px, py))
        if len(segmen) > 1:
            self._gambar_segmen(segmen, b.warna, turunan)

    def _gambar_segmen(self, segmen, warna, turunan=False):
        titik = [v for p in segmen for v in p]
        if turunan:
            self.kanvas.create_line(*titik, fill=warna, width=2, dash=(5, 4))
        else:
            self.kanvas.create_line(*titik, fill=warna, width=2, smooth=True)

    # ---------- titik penting & analisis teks ----------
    def _rentang_x(self, lebar):
        x0, _ = self._ke_dunia(0, 0)
        x1, _ = self._ke_dunia(lebar, 0)
        return x0, x1

    def _tandai_titik(self, aktif, lebar, tinggi):
        if not aktif:
            return
        x0, x1 = self._rentang_x(lebar)
        b = self.baris_aktif if self.baris_aktif in aktif else aktif[0]
        f = lambda x: nilai_aman(b.poohon, self._env(x))
        titik = [(r, 0.0) for r in cari_akar(f, x0, x1)]
        y0 = f(0.0)
        if not math.isnan(y0):
            titik.append((0.0, y0))
        for (wx, wy) in titik:
            px, py = self._ke_layar(wx, wy)
            if -20 <= px <= lebar + 20 and -20 <= py <= tinggi + 20:
                self.kanvas.create_oval(px - 4, py - 4, px + 4, py + 4,
                                        fill="#ffffff", outline=b.warna, width=2)
                self.kanvas.create_text(
                    px + 8, py - 8, anchor="w", fill=TEKS,
                    font=("Segoe UI", 9, "bold"),
                    text="(%s, %s)" % (fmt(wx), fmt(wy)))

    def _isi_analisis(self, aktif, lebar):
        baris_teks = []
        x0, x1 = self._rentang_x(lebar)
        for i, b in enumerate(aktif, 1):
            f = lambda x, bb=b: nilai_aman(bb.poohon, self._env(x))
            baris_teks.append("Fungsi %d: y = %s" % (i, b.teks()))
            y0 = f(0.0)
            baris_teks.append("  Potong sumbu Y : (0, %s)" % fmt(y0))
            akar = cari_akar(f, x0, x1)
            if akar:
                baris_teks.append("  Potong sumbu X : " + ", ".join(
                    "(%s, 0)" % fmt(r) for r in akar))
            else:
                baris_teks.append("  Potong sumbu X : tidak ada di layar")
            if b.var_turunan.get():
                baris_teks.append("  Garis putus-putus = turunan f'(x)")
            baris_teks.append("")
        for i in range(len(aktif) - 1):
            f1 = lambda x, bb=aktif[i]: nilai_aman(bb.poohon, self._env(x))
            f2 = lambda x, bb=aktif[i + 1]: nilai_aman(bb.poohon, self._env(x))
            potong = cari_akar(lambda x: f1(x) - f2(x), x0, x1)
            if potong:
                baris_teks.append("Titik potong fungsi %d & %d:" % (i + 1, i + 2))
                for r in potong:
                    baris_teks.append("  (%s, %s)" % (fmt(r), fmt(f1(r))))
                baris_teks.append("")
        if aktif:
            b = self.baris_aktif if self.baris_aktif in aktif else aktif[0]
            f = lambda x: nilai_aman(b.poohon, self._env(x))
            baris_teks.append("Tabel titik: y = %s" % b.teks())
            xa, xb = max(math.ceil(x0), -50), min(math.floor(x1), 50)
            for xi in range(xa, xb + 1):
                baris_teks.append("  x = %3d  ->  y = %s" % (xi, fmt(f(float(xi)))))
        teks = "\n".join(baris_teks) if baris_teks else \
            "Belum ada fungsi yang tergambar."
        self.teks_analisis.delete("1.0", "end")
        self.teks_analisis.insert("1.0", teks)

    def _salin_analisis(self):
        self.clipboard_clear()
        self.clipboard_append(self.teks_analisis.get("1.0", "end").strip())
        self.status.config(text="Teks analisis disalin.")

    # ---------- interaksi bidang ----------
    def zoom(self, faktor, cx=None, cy=None):
        lebar = max(self.kanvas.winfo_width(), 50)
        tinggi = max(self.kanvas.winfo_height(), 50)
        if cx is None:
            cx, cy = lebar / 2, tinggi / 2
        else:
            self._ikut_tengah = False
        wx, wy = self._ke_dunia(cx, cy)
        self.skala = min(max(self.skala * faktor, 3.0), 4000.0)
        self.ox = cx - wx * self.skala
        self.oy = cy + wy * self.skala
        self.gambar()

    def atur_ulang(self, tanpa_gambar=False):
        self.skala = 45.0
        self._ikut_tengah = True
        if not tanpa_gambar:
            self.gambar()

    def _roda_mouse(self, e):
        if e.delta > 0:
            self.zoom(1.12, e.x, e.y)
        else:
            self.zoom(0.89, e.x, e.y)

    def _mulai_seret(self, e):
        self._seret = (e.x, e.y)

    def _seret_mouse(self, e):
        if not self._seret:
            return
        self._ikut_tengah = False
        dx, dy = e.x - self._seret[0], e.y - self._seret[1]
        self.ox += dx
        self.oy += dy
        self._seret = (e.x, e.y)
        self.gambar()

    def _gerak_mouse(self, e):
        wx, wy = self._ke_dunia(e.x, e.y)
        teks = "Posisi kursor: (%s, %s)" % (fmt(wx, 2), fmt(wy, 2))
        for b in self.baris:
            if b.poohon is not None and b.var_tampil.get():
                y = nilai_aman(b.poohon, self._env(wx))
                if not math.isnan(y) and abs(y) < 1e9:
                    teks += "   |   y = %s : %s" % (b.teks(), fmt(y))
                    break
        self.status.config(text=teks)

    # ---------- ekspor PNG (butuh Pillow) ----------
    def simpan_png(self):
        if not PUNYA_PIL:
            messagebox.showinfo(
                "Simpan PNG",
                "Fitur ini butuh pustaka Pillow. Di berkas .exe resmi "
                "Pillow sudah termasuk, jadi tombol ini berfungsi di sana.")
            return
        berkas = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("Gambar PNG", "*.png")],
            initialfile="grafik.png")
        if not berkas:
            return
        L, T = 1800, 1200
        img = Image.new("RGB", (L, T), (10, 17, 32))
        d = ImageDraw.Draw(img)
        skala = self.skala * (L / max(self.kanvas.winfo_width(), 50))
        ox, oy = L / 2 + (self.ox - self.kanvas.winfo_width() / 2) * (L / max(self.kanvas.winfo_width(), 50)), \
                 T / 2 + (self.oy - self.kanvas.winfo_height() / 2) * (T / max(self.kanvas.winfo_height(), 50))
        x0, x1 = (0 - ox) / skala, (L - ox) / skala
        y0, y1 = (oy - T) / skala, oy / skala
        for gx in range(math.floor(x0), math.ceil(x1) + 1):
            px = ox + gx * skala
            d.line([(px, 0), (px, T)], fill=(27, 42, 69))
        for gy in range(math.floor(y0), math.ceil(y1) + 1):
            py = oy - gy * skala
            d.line([(0, py), (L, py)], fill=(27, 42, 69))
        d.line([(0, oy), (L, oy)], fill=(84, 116, 158), width=3)
        d.line([(ox, 0), (ox, T)], fill=(84, 116, 158), width=3)
        for b in self.baris:
            if b.poohon is None or not b.var_tampil.get():
                continue
            f = lambda x, bb=b: nilai_aman(bb.poohon, self._env(x))
            segmen = []
            for px in range(0, L + 1, 2):
                wx = (px - ox) / skala
                wy = f(wx)
                if math.isnan(wy) or math.isinf(wy):
                    if len(segmen) > 1:
                        d.line(segmen, fill=b.warna, width=3)
                    segmen = []
                    continue
                py = oy - wy * skala
                if segmen and abs(py - segmen[-1][1]) > T * 1.5:
                    if len(segmen) > 1:
                        d.line(segmen, fill=b.warna, width=3)
                    segmen = []
                segmen.append((px, py))
            if len(segmen) > 1:
                d.line(segmen, fill=b.warna, width=3)
        img.save(berkas)
        self.status.config(text="Grafik disimpan ke " + berkas)


if __name__ == "__main__":
    Aplikasi().mainloop()
