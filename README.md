# Kalkulator Grafik

Aplikasi Windows untuk menggambar kurva persamaan matematika di bidang
kartesius (terinspirasi Desmos). Ditulis dengan Python + Tkinter dalam satu
berkas: `kalkulator_grafik.py`. Tanpa eval — parser rumusnya ditulis sendiri
dan aman.

## Fitur

- Banyak fungsi sekaligus, tiap fungsi berwarna sendiri (klik titik warna
  untuk mengganti warna kurva).
- Rumus lengkap: pangkat `^`, akar `sqrt`, `sin/cos/tan`, `log` (basis 10),
  `ln`, nilai mutlak `|x|`, konstanta `pi` dan `e`.
- Perkalian implisit ala Desmos: `2x`, `3(x+1)`, `xy`. Koma desimal Indonesia
  (`0,5`) diterima.
- Slider parameter otomatis: huruf selain x (mis. `a*x + b`) menjadi
  penggeser yang menggerakkan kurva secara langsung.
- Titik dicari sendiri oleh program: titik potong sumbu X dan Y, titik potong
  antar kurva, dan tabel titik (x, y) — semua juga tampil sebagai teks di
  panel "Titik & Analisis" (bisa disalin).
- Kurva turunan f'(x) per fungsi (tombol f′), zoom (tombol/scroll), geser
  bidang (drag), simpan grafik sebagai PNG.
- Menu "Contoh Rumus" berisi contoh siap pakai.

## Menjalankan dari sumber

Butuh Python 3.10+ (Tkinter sudah bawaan). Untuk ekspor PNG pasang Pillow:

```
pip install pillow
python kalkulator_grafik.py
```

## Membuat .exe Windows

Repo ini punya GitHub Actions (`.github/workflows/build-exe.yml`): setiap
push ke `main` (atau jalankan manual dari tab Actions) akan membuild
`KalkulatorGrafik.exe` di mesin Windows dan menyediakannya sebagai artifact
`KalkulatorGrafik-exe` yang bisa diunduh. EXE-nya satu berkas, portable —
klik dua kali langsung jalan, tanpa instal Python.
