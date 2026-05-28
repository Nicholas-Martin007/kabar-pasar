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

const OPEN_MIN  = 9 * 60;  // 09:00 WIB
const CLOSE_MIN = 15 * 60; // 15:00 WIB

export function getMarketStatus(): MarketStatus {
  const wib    = wibNow();
  const day    = wib.getUTCDay(); // 0=Sun … 6=Sat
  const totalM = wib.getUTCHours() * 60 + wib.getUTCMinutes();
  const isWeekday = day >= 1 && day <= 5;
  const isOpen    = isWeekday && totalM >= OPEN_MIN && totalM < CLOSE_MIN;

  if (isOpen) {
    const rem = CLOSE_MIN - totalM;
    const h   = Math.floor(rem / 60);
    const m   = rem % 60;
    return {
      isOpen: true,
      label:  h > 0 ? `Tutup dalam ${h}j ${m}m` : `Tutup dalam ${m}m`,
    };
  }

  if (isWeekday && totalM < OPEN_MIN) {
    return { isOpen: false, label: 'Buka pukul 09:00 WIB' };
  }

  const DAY_ID = ['Min', 'Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab'];
  for (let skip = 1; skip <= 7; skip++) {
    const nextDay = (day + skip) % 7;
    if (nextDay >= 1 && nextDay <= 5) {
      return {
        isOpen: false,
        label:  skip === 1 ? 'Buka besok 09:00 WIB' : `Buka ${DAY_ID[nextDay]} 09:00 WIB`,
      };
    }
  }

  return { isOpen: false, label: 'Buka Senin 09:00 WIB' };
}
