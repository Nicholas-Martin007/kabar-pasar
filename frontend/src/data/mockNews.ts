import { News } from '@/src/types/news';

const now = Date.now();
const ago = (hours: number, mins = 0) =>
  new Date(now - (hours * 60 + mins) * 60_000).toISOString();

export const mockNews: News[] = [
  // ── REGULATORY ──────────────────────────────────────────────────────────────
  {
    id: 'reg-001',
    title: 'BEI Suspensi Saham BUMI Atas Keterlambatan Laporan Keuangan FY2025',
    source: 'BEI',
    publishedAt: ago(1),
    importance: 'high',
    category: 'regulatory',
    tickers: ['BUMI'],
    url: 'https://www.idx.co.id/id/perusahaan-tercatat/pengumuman-perusahaan/',
    excerpt:
      'Bursa Efek Indonesia menghentikan sementara perdagangan saham BUMI per 27 Mei 2026 karena emiten belum menyampaikan laporan keuangan FY2025 melampaui tenggat regulasi OJK.',
    aiSummary: [
      'BEI menghentikan perdagangan BUMI efektif 27 Mei 2026 atas keterlambatan laporan keuangan FY2025 yang melebihi batas waktu OJK.',
      'Suspensi berlaku hingga emiten memenuhi kewajiban keterbukaan informasi; saham BUMI turun 4,8% sehari sebelum suspensi.',
      'Pemegang saham disarankan memantau situs resmi BEI dan pengumuman resmi BUMI secara berkala.',
    ],
  },
  {
    id: 'reg-002',
    title: 'OJK Perketat Rasio Margin Trading: dari 1:5 Menjadi 1:3, Berlaku 1 Agustus 2026',
    source: 'BEI',
    publishedAt: ago(10),
    importance: 'high',
    category: 'regulatory',
    tickers: [],
    url: 'https://www.idx.co.id/id/perusahaan-tercatat/pengumuman-perusahaan/',
    excerpt:
      'Otoritas Jasa Keuangan resmi menetapkan aturan baru rasio pembiayaan margin trading dari 1:5 menjadi 1:3 yang akan berlaku efektif pada 1 Agustus 2026 untuk seluruh sekuritas.',
    aiSummary: [
      'OJK menurunkan rasio pembiayaan margin trading dari 1:5 menjadi 1:3, berlaku 1 Agustus 2026 di seluruh anggota bursa.',
      'Aturan diperkirakan mengurangi posisi margin aktif hingga 30%, berpotensi menekan volume harian jangka pendek.',
      'OJK menilai perubahan ini penting untuk memitigasi risiko sistemik di tengah meningkatnya volatilitas pasar global.',
    ],
  },

  // ── CORPORATE ACTIONS ────────────────────────────────────────────────────────
  {
    id: 'ca-001',
    title: 'BBCA Umumkan Dividen Interim Rp 340/Saham, Melampaui Konsensus Analis',
    source: 'BEI',
    publishedAt: ago(2),
    importance: 'high',
    category: 'corporate_action',
    tickers: ['BBCA'],
    url: 'https://www.idx.co.id/id/perusahaan-tercatat/pengumuman-perusahaan/',
    excerpt:
      'Bank Central Asia menetapkan dividen interim sebesar Rp 340 per saham untuk tahun buku 2026, melampaui estimasi konsensus analis di Rp 310 per saham dengan cum-dividen pada 12 Juni 2026.',
    aiSummary: [
      'BBCA menetapkan dividen interim Rp 340/saham, 9,7% lebih tinggi dari konsensus analis Rp 310/saham.',
      'Dividend yield berdasarkan harga penutupan terakhir mencapai 2,1%, di atas rata-rata sektor perbankan 1,8%.',
      'Cum-dividen 12 Juni 2026 — investor yang ingin menerima dividen harus memegang saham sebelum tanggal tersebut.',
    ],
  },
  {
    id: 'ca-002',
    title: 'BREN Rencana Rights Issue Rp 5 Triliun untuk Ekspansi Kapasitas EBT di Sulawesi',
    source: 'IR Emiten',
    publishedAt: ago(7),
    importance: 'medium',
    category: 'corporate_action',
    tickers: ['BREN'],
    url: 'https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/',
    excerpt:
      'Barito Renewables Energy berencana menerbitkan rights issue senilai Rp 5 triliun dengan rasio 1:4 yang dananya akan dialokasikan untuk pengembangan proyek PLTP dan PLTS berkapasitas 1.200 MW di Sulawesi.',
    aiSummary: [
      'BREN akan rights issue Rp 5 triliun (rasio 1:4) untuk mendanai proyek PLTP dan PLTS 1.200 MW di Sulawesi, target operasional 2028.',
      'Dilusi akibat rights issue diperkirakan ~20%; saham BREN telah naik 31% YTD sebelum pengumuman ini.',
      'Dana segar memperkuat posisi BREN sebagai pengembang EBT terbesar Indonesia dalam jangka menengah.',
    ],
  },
  {
    id: 'ca-003',
    title: 'TLKM RUPS Tahunan 15 Juni 2026: Agenda Pemilihan Direksi dan Dividen Final Rp 180/Saham',
    source: 'IR Emiten',
    publishedAt: ago(12),
    importance: 'medium',
    category: 'corporate_action',
    tickers: ['TLKM'],
    url: 'https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/',
    excerpt:
      'Telkom Indonesia menggelar Rapat Umum Pemegang Saham Tahunan pada 15 Juni 2026, dengan agenda utama persetujuan laporan keuangan FY2025, pemilihan direksi periode 2026–2029, dan pengesahan dividen final.',
    aiSummary: [
      'RUPS Tahunan TLKM 15 Juni 2026: agenda utama pemilihan direksi baru dan pengesahan dividen final Rp 180/saham (yield ~1,7%).',
      'Pemerintah (52,09% saham) mengusulkan petahana Direktur Utama untuk periode 2026–2029; keputusan final di RUPS.',
      'Agenda transformasi digital dan perampingan lini bisnis non-inti Telkom Group juga akan dibahas dalam RUPS.',
    ],
  },
  {
    id: 'ca-004',
    title: 'ASII Akuisisi 30% Saham Minoritas Astratel Nusantara Senilai Rp 1,8 Triliun',
    source: 'IR Emiten',
    publishedAt: ago(30),
    importance: 'medium',
    category: 'corporate_action',
    tickers: ['ASII'],
    url: 'https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/',
    excerpt:
      'Astra International mengakuisisi 30% saham minoritas PT Astratel Nusantara senilai Rp 1,8 triliun, meningkatkan kepemilikan menjadi 95,2% dan memperkuat integrasi bisnis infrastruktur telekomunikasi.',
    aiSummary: [
      'ASII akuisisi 30% saham Astratel Nusantara (Rp 1,8 T), kepemilikan naik ke 95,2% untuk memperkuat integrasi bisnis infrastruktur telko.',
      'Transaksi diperkirakan menambah EPS konsolidasi ASII Rp 12–18/saham mulai FY2026 setelah full konsolidasi.',
      'Langkah ini sejalan dengan strategi ASII memaksimalkan sinergi lintas segmen bisnis menjelang rotasi digital.',
    ],
  },
  {
    id: 'ca-005',
    title: 'BMRI Ajukan Rencana Stock Split 1:2 ke OJK, Keputusan Diharapkan dalam 30 Hari Kerja',
    source: 'BEI',
    publishedAt: ago(34),
    importance: 'medium',
    category: 'corporate_action',
    tickers: ['BMRI'],
    url: 'https://www.idx.co.id/id/perusahaan-tercatat/pengumuman-perusahaan/',
    excerpt:
      'Bank Mandiri secara resmi mengajukan permohonan persetujuan aksi korporasi stock split dengan rasio 1:2 kepada OJK untuk meningkatkan likuiditas dan aksesibilitas saham bagi investor ritel.',
    aiSummary: [
      'BMRI mengajukan stock split 1:2 ke OJK; persetujuan diharapkan dalam 30 hari kerja — harga saham saat ini ~Rp 7.750/lembar.',
      'Tujuan: meningkatkan likuiditas dan aksesibilitas saham BMRI bagi investor ritel yang terhalang harga tinggi.',
      'Historis, stock split blue-chip IDX rata-rata direspons positif pasar dalam 30 hari pertama pasca-efektif.',
    ],
  },

  // ── EARNINGS ────────────────────────────────────────────────────────────────
  {
    id: 'earn-001',
    title: 'BBRI Cetak Laba Bersih Q1 2026 Rp 15,7 Triliun, Tumbuh 12% YoY',
    source: 'IR Emiten',
    publishedAt: ago(5),
    importance: 'high',
    category: 'earnings',
    tickers: ['BBRI'],
    url: 'https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/',
    excerpt:
      'Bank Rakyat Indonesia membukukan laba bersih kuartal pertama 2026 sebesar Rp 15,7 triliun, tumbuh 12% dibanding periode yang sama tahun lalu, didorong ekspansi kredit UMKM dan perbaikan kualitas aset.',
    aiSummary: [
      'BBRI cetak laba bersih Q1 2026 Rp 15,7 T (+12% YoY), melampaui estimasi konsensus Rp 14,9 T berkat pertumbuhan kredit UMKM.',
      'NPL gross membaik dari 3,1% menjadi 2,7%; margin bunga bersih (NIM) terjaga di 7,2%, di atas estimasi 7,0%.',
      'Pertumbuhan kredit UMKM +18% YoY menjadi katalis utama; manajemen optimistis target laba FY2026 Rp 62 T tercapai.',
    ],
  },
  {
    id: 'earn-002',
    title: 'GOTO Catat Revenue GoPay Tumbuh 28% YoY, Operating Loss Menyempit 42% di Q1 2026',
    source: 'IR Emiten',
    publishedAt: ago(14),
    importance: 'medium',
    category: 'earnings',
    tickers: ['GOTO'],
    url: 'https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/',
    excerpt:
      'GoTo Group melaporkan pertumbuhan revenue GoPay sebesar 28% YoY di kuartal pertama 2026, sementara operating loss konsolidasi menyempit 42% YoY menjadi Rp 1,1 triliun dengan proyeksi break-even di Q3 2026.',
    aiSummary: [
      'GoPay tumbuh 28% YoY; operating loss GOTO menyempit 42% YoY ke Rp 1,1 T — manajemen proyeksikan break-even operasional Q3 2026.',
      'GMV GoTo Logistics +19% YoY, menunjukkan diversifikasi revenue solid di luar segmen ride-hailing yang mulai mature.',
      'Saham GOTO diperdagangkan di 6,8x EV/Revenue 2026E — premium terhadap peer Asia Tenggara, namun didukung tren profitabilitas membaik.',
    ],
  },
  {
    id: 'earn-003',
    title: 'UNVR Catat Pendapatan Q1 2026 Turun 3% YoY, Tekanan Daya Beli Kelas Menengah Bawah',
    source: 'Kontan',
    publishedAt: ago(38),
    importance: 'low',
    category: 'earnings',
    tickers: ['UNVR'],
    url: 'https://www.kontan.co.id/news/pasar-modal',
    excerpt:
      'Unilever Indonesia membukukan pendapatan kuartal pertama 2026 sebesar Rp 10,4 triliun, turun 3% YoY, terbebani tekanan daya beli konsumen segmen menengah bawah dan persaingan private label yang kian ketat.',
    aiSummary: [
      'Pendapatan UNVR Q1 2026 turun 3% YoY ke Rp 10,4 T; segmen home & personal care paling terdampak dengan penurunan volume -5% YoY.',
      'Segmen foods & refreshment relatif stabil; tekanan margin datang dari biaya bahan baku dan promosi untuk mempertahankan pangsa pasar.',
      'Manajemen pertahankan target margin EBITDA 19–21%; efisiensi biaya operasional menjadi prioritas utama FY2026.',
    ],
  },

  // ── MARKET NEWS ─────────────────────────────────────────────────────────────
  {
    id: 'mkt-001',
    title: 'IHSG Rebound 1,2% ke 7.312 Setelah Tiga Sesi Beruntun Melemah',
    source: 'CNBC Indonesia',
    publishedAt: ago(8),
    importance: 'medium',
    category: 'market_news',
    tickers: ['BBCA', 'BBRI', 'BMRI'],
    url: 'https://www.cnbcindonesia.com/market/',
    excerpt:
      'Indeks Harga Saham Gabungan ditutup menguat 1,2% ke level 7.312 setelah melemah selama tiga sesi perdagangan berturut-turut, dipicu data inflasi AS yang lebih lunak dari perkiraan.',
    aiSummary: [
      'IHSG rebound 1,2% ke 7.312, memutus tiga sesi pelemahan berturut-turut, dipicu inflasi AS April lebih rendah dari estimasi.',
      'Sektor perbankan big-4 memimpin dengan rata-rata kenaikan 1,8%; net foreign buy Rp 523 M — pertama kali positif dalam sepekan.',
      'Volume transaksi Rp 11,4 T, di atas rata-rata 20 hari (Rp 9,8 T) — sinyal minat beli yang menguat dari investor institusional.',
    ],
  },
  {
    id: 'mkt-002',
    title: 'MEDC Naik 7,1% Seiring Harga Minyak Brent Tembus $85/bbl Pertama Kali dalam 8 Bulan',
    source: 'Bisnis Indonesia',
    publishedAt: ago(18),
    importance: 'medium',
    category: 'market_news',
    tickers: ['MEDC'],
    url: 'https://www.bisnis.com/pasar-modal/',
    excerpt:
      'Saham Medco Energi Internasional menguat 7,1% menyusul lonjakan harga minyak mentah Brent menembus level $85 per barel untuk pertama kalinya dalam delapan bulan, didorong penurunan stok AS yang lebih dalam dari perkiraan.',
    aiSummary: [
      'MEDC naik 7,1% seiring Brent tembus $85/bbl — katalis utama: stok minyak AS turun 3,2 juta barel vs estimasi 0,8 juta barel.',
      'Setiap kenaikan $5/bbl Brent diperkirakan menambah EBITDA MEDC ~Rp 280–320 M secara annualized, menurut estimasi analis.',
      'Ketegangan geopolitik di Timur Tengah menambah tekanan sisi penawaran; pasar memperkirakan Brent bisa bertahan di $82–88 jangka pendek.',
    ],
  },
  {
    id: 'mkt-003',
    title: 'ANTM Melonjak 5,3% Seiring Nikel LME Naik 4,1% ke $18.750/Ton Akibat Pembatasan Filipina',
    source: 'Kontan',
    publishedAt: ago(24),
    importance: 'medium',
    category: 'market_news',
    tickers: ['ANTM'],
    url: 'https://www.kontan.co.id/news/pasar-modal',
    excerpt:
      'Saham Aneka Tambang menguat 5,3% mengikuti lonjakan harga nikel di London Metal Exchange ke $18.750 per ton setelah pemerintah Filipina mengumumkan pembatasan ekspor bijih nikel yang mengejutkan pasar.',
    aiSummary: [
      'ANTM naik 5,3% seiring nikel LME melonjak 4,1% ke $18.750/ton — pemicunya pengumuman pembatasan ekspor nikel dari Filipina.',
      'Valuasi ANTM saat ini 6,2x EV/EBITDA 2026E, di bawah rata-rata historis 7,5x — ada ruang upside jika harga nikel bertahan.',
      'Rencana smelter nikel kelas-1 bersama Mitsubishi (target operasional 2028) menjadi katalis jangka menengah yang solid.',
    ],
  },
  {
    id: 'mkt-004',
    title: 'Sektor Perbankan Kompak Menguat, Pimpin Kenaikan IHSG Ditopang Data Kredit Maret',
    source: 'CNBC Indonesia',
    publishedAt: ago(48),
    importance: 'low',
    category: 'market_news',
    tickers: ['BBCA', 'BBRI', 'BMRI', 'INDF'],
    url: 'https://www.cnbcindonesia.com/market/',
    excerpt:
      'Saham-saham perbankan besar ditutup kompak menguat dengan kenaikan rata-rata 1,1%, memimpin kenaikan Indeks Harga Saham Gabungan setelah rilisnya data penyaluran kredit perbankan nasional Maret 2026.',
    aiSummary: [
      'Perbankan big-4 rata-rata naik 1,1%, memimpin IHSG setelah data kredit nasional Maret 2026 tumbuh 10,8% YoY, di atas estimasi 9,5%.',
      'Net foreign buy sektor perbankan Rp 780 M — aliran dana asing terbesar dalam dua pekan terakhir ke sektor ini.',
      'Pertumbuhan kredit yang solid mengindikasikan momentum ekonomi domestik masih kuat memasuki Q2 2026.',
    ],
  },

  // ── MACRO ────────────────────────────────────────────────────────────────────
  {
    id: 'mac-001',
    title: 'Bank Indonesia Pertahankan BI Rate di 5,75%, Prioritaskan Stabilitas Rupiah',
    source: 'CNBC Indonesia',
    publishedAt: ago(3),
    importance: 'high',
    category: 'macro',
    tickers: [],
    url: 'https://www.cnbcindonesia.com/market/',
    excerpt:
      'Bank Indonesia kembali mempertahankan suku bunga acuan BI Rate di level 5,75% dalam Rapat Dewan Gubernur Mei 2026, dengan alasan menjaga stabilitas nilai tukar rupiah dan mengendalikan inflasi yang terjaga di 2,8% YoY.',
    aiSummary: [
      'BI Rate dipertahankan di 5,75% sesuai ekspektasi konsensus; Gubernur BI menyebut stabilitas rupiah dan inflasi 2,8% YoY sebagai alasan.',
      'Pasar memprakirakan satu pemangkasan 25 bps di Q4 2026, bergantung pada arah FFR The Fed dan perkembangan inflasi domestik.',
      'Keputusan ini mendukung sentimen positif aset fixed income IDR; yield SBN 10Y diprakirakan stabil di kisaran 6,7–6,9%.',
    ],
  },
];
