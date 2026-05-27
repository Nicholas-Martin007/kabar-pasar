import { NewsItem } from '@/types/news';

const now = Date.now();
const mins = (n: number) => new Date(now - n * 60 * 1000).toISOString();
const hrs = (n: number) => new Date(now - n * 60 * 60 * 1000).toISOString();

export const MOCK_NEWS: NewsItem[] = [
  {
    id: '1',
    title: 'BEI Suspensi Saham BUMI Terkait Keterlambatan Laporan Keuangan Tahunan 2024',
    aiSummary:
      'Bursa Efek Indonesia menghentikan sementara perdagangan saham BUMI efektif hari ini. Suspensi dipicu keterlambatan penyampaian laporan keuangan FY2024 melebihi batas regulasi OJK.',
    source: 'IDX',
    publishedAt: mins(3),
    importance: 'critical',
    ticker: 'BUMI',
    priceChange: -4.2,
    category: 'announcement',
    isRead: false,
    isBookmarked: false,
  },
  {
    id: '2',
    title: 'BBCA Umumkan Dividen Interim Rp 340 per Saham untuk Tahun Buku 2025',
    aiSummary:
      'Bank Central Asia menetapkan dividen interim Rp 340/saham, melampaui estimasi konsensus analis di Rp 310. Dividend yield mencapai 2,1% berdasarkan harga penutupan kemarin.',
    source: 'IDX',
    publishedAt: mins(15),
    importance: 'high',
    ticker: 'BBCA',
    priceChange: 1.23,
    category: 'announcement',
    isRead: false,
    isBookmarked: true,
  },
  {
    id: '3',
    title: 'IHSG Dibuka Menguat 0,8% Dipimpin Sektor Perbankan dan Telekomunikasi',
    aiSummary:
      'Indeks Harga Saham Gabungan mengawali sesi pagi secara positif, ditopang data inflasi April yang lebih rendah dari perkiraan. Sektor bank big-4 dan TLKM kompak menguat di awal perdagangan.',
    source: 'CNBC Indonesia',
    publishedAt: mins(42),
    importance: 'medium',
    category: 'market',
    isRead: true,
    isBookmarked: false,
  },
  {
    id: '4',
    title: 'Telkom Indonesia Raih Kontrak Infrastruktur Data Center Rp 2,3 Triliun dari Pemerintah',
    aiSummary:
      'TLKM memenangkan tender proyek pembangunan pusat data nasional tahap II senilai Rp 2,3 triliun. Kontrak ini memperkuat pipeline pendapatan segmen enterprise hingga 2027.',
    source: 'Bisnis Indonesia',
    publishedAt: mins(78),
    importance: 'high',
    ticker: 'TLKM',
    priceChange: 2.45,
    category: 'announcement',
    isRead: false,
    isBookmarked: false,
  },
  {
    id: '5',
    title: 'Fed Tahan Suku Bunga di 5,25–5,50%, Isyaratkan Dua Pemangkasan Akhir 2025',
    aiSummary:
      'Federal Reserve mempertahankan suku bunga acuan dan memproyeksikan dua kali penurunan rate di semester II 2025. Pasar memperkirakan dampak positif bagi arus modal masuk ke aset emerging market termasuk Indonesia.',
    source: 'Reuters',
    publishedAt: hrs(2),
    importance: 'high',
    category: 'macro',
    isRead: false,
    isBookmarked: false,
  },
  {
    id: '6',
    title: 'Astra International Rilis Penjualan Mobil April: Turun 6% YoY, Honda CR-V Topang Kinerja',
    aiSummary:
      'ASII mencatat penjualan 47.200 unit di April 2025, turun 6% dibandingkan April 2024. Segmen SUV premium, terutama Honda CR-V, menjadi penopang di tengah tekanan daya beli segmen entry-level.',
    source: 'Kontan',
    publishedAt: hrs(3),
    importance: 'medium',
    ticker: 'ASII',
    priceChange: -0.87,
    category: 'sector',
    isRead: true,
    isBookmarked: false,
  },
  {
    id: '7',
    title: 'Harga CPO Naik 3,2% Pekan Ini Seiring Penurunan Stok Malaysia dan Permintaan India',
    aiSummary:
      'Harga minyak kelapa sawit mentah di Bursa Malaysia menguat didukung laporan penurunan stok akhir April dan kenaikan permintaan dari India. Saham-saham CPO domestik seperti AALI dan SIMP berpotensi mendapat katalis positif.',
    source: 'Bisnis Indonesia',
    publishedAt: hrs(4),
    importance: 'medium',
    category: 'sector',
    isRead: true,
    isBookmarked: true,
  },
  {
    id: '8',
    title: 'OJK Keluarkan Aturan Baru Margin Trading: Rasio Pembiayaan Turun dari 1:5 Jadi 1:3',
    aiSummary:
      'Otoritas Jasa Keuangan memperketat regulasi margin trading efektif 1 Juli 2025. Perubahan rasio dari 1:5 ke 1:3 berpotensi menekan volume transaksi short-term, namun dinilai perkuat stabilitas pasar jangka panjang.',
    source: 'CNBC Indonesia',
    publishedAt: hrs(5),
    importance: 'high',
    category: 'macro',
    isRead: true,
    isBookmarked: false,
  },
  {
    id: '9',
    title: 'Nvidia Lampaui Ekspektasi Q1 2025: Pendapatan Data Center Sentuh $22,6 Miliar',
    aiSummary:
      'Nvidia melaporkan pendapatan Q1 FY2026 sebesar $44,1 miliar, melampaui estimasi Wall Street. Segmen data center tumbuh 73% YoY, didorong lonjakan permintaan chip H100 dan Blackwell dari hyperscalers global.',
    source: 'CNBC Global',
    publishedAt: hrs(6),
    importance: 'medium',
    category: 'global',
    isRead: true,
    isBookmarked: false,
  },
];
