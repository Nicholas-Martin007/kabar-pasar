const WIB_OFFSET_MS = 7 * 60 * 60 * 1000; // UTC+7

function wibNow(): Date {
  return new Date(Date.now() + WIB_OFFSET_MS);
}

export function getGreeting(): string {
  const h = wibNow().getUTCHours();
  if (h < 11) return 'Selamat pagi';
  if (h < 15) return 'Selamat siang';
  if (h < 18) return 'Selamat sore';
  return 'Selamat malam';
}

export interface MarketStatus {
  isOpen: boolean;
  label: string;
}

const DAY_ID = ['Min', 'Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab'];

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

function hhmm(min: number): string {
  return `${pad2(Math.floor(min / 60))}:${pad2(min % 60)}`;
}

/**
 * IDX trading sessions in WIB minutes, per weekday (with lunch break):
 *   Mon–Thu: 09:00–12:00, 13:30–15:00
 *   Fri:     09:00–11:30, 14:00–15:00
 * Weekend: none.
 */
function sessionsFor(day: number): [number, number][] {
  if (day === 5) return [[540, 690], [840, 900]]; // Friday
  if (day >= 1 && day <= 4) return [[540, 720], [810, 900]]; // Mon–Thu
  return [];
}

export function getMarketStatus(): MarketStatus {
  const wib    = wibNow();
  const day    = wib.getUTCDay(); // 0=Sun … 6=Sat
  const totalM = wib.getUTCHours() * 60 + wib.getUTCMinutes();
  const sessions = sessionsFor(day);

  // Open during a session?
  for (const [start, end] of sessions) {
    if (totalM >= start && totalM < end) {
      const rem = end - totalM;
      const h = Math.floor(rem / 60);
      const m = rem % 60;
      return {
        isOpen: true,
        label: h > 0 ? `Tutup dalam ${h}j ${m}m` : `Tutup dalam ${m}m`,
      };
    }
  }

  // Lunch break — between session 1 and session 2.
  if (sessions.length === 2 && totalM >= sessions[0][1] && totalM < sessions[1][0]) {
    return { isOpen: false, label: `Istirahat — buka ${hhmm(sessions[1][0])} WIB` };
  }

  // Before today's first session.
  if (sessions.length && totalM < sessions[0][0]) {
    return { isOpen: false, label: `Buka pukul ${hhmm(sessions[0][0])} WIB` };
  }

  // After close / weekend → next trading day.
  for (let skip = 1; skip <= 7; skip++) {
    const nextDay = (day + skip) % 7;
    const ns = sessionsFor(nextDay);
    if (ns.length) {
      const at = hhmm(ns[0][0]);
      return {
        isOpen: false,
        label: skip === 1 ? `Buka besok ${at} WIB` : `Buka ${DAY_ID[nextDay]} ${at} WIB`,
      };
    }
  }

  return { isOpen: false, label: 'Buka Senin 09:00 WIB' };
}
