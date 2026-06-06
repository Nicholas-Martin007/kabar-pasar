import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Colors, FontFamily, FontSize, FontWeight } from '@/src/theme';
import { Candle } from '@/src/services/api';

interface Props {
  candles: Candle[];
  width: number;
  height: number;
}

function formatIDR(price: number): string {
  return Math.round(price)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

/**
 * Lightweight candlestick chart built from plain Views (no SVG dependency),
 * matching the LineChart approach. Green candle = close ≥ open, red otherwise.
 */
export function CandlestickChart({ candles, width, height }: Props) {
  if (candles.length === 0) {
    return <View style={{ width, height }} />;
  }

  const max = Math.max(...candles.map((c) => c.h));
  const min = Math.min(...candles.map((c) => c.l));
  const range = max - min || 1;
  const pad = height * 0.1;
  const usable = height - pad * 2;
  const y = (price: number) => pad + ((max - price) / range) * usable;

  const col = width / candles.length;
  const bodyW = Math.max(2, Math.min(col * 0.6, 12));

  return (
    <View style={{ width, height }}>
      <Text style={[styles.yLabel, { top: 0 }]}>{formatIDR(max)}</Text>
      <Text style={[styles.yLabel, { bottom: 0 }]}>{formatIDR(min)}</Text>

      {candles.map((cd, i) => {
        const up = cd.c >= cd.o;
        const color = up ? Colors.sentiment.positive : Colors.sentiment.negative;
        const cx = i * col + col / 2;
        const yHigh = y(cd.h);
        const yLow = y(cd.l);
        const bodyTop = Math.min(y(cd.o), y(cd.c));
        const bodyH = Math.max(1, Math.abs(y(cd.c) - y(cd.o)));

        return (
          <React.Fragment key={i}>
            {/* Wick (high → low) */}
            <View
              style={{
                position: 'absolute',
                left: cx - 0.5,
                top: yHigh,
                width: 1,
                height: Math.max(1, yLow - yHigh),
                backgroundColor: color,
              }}
            />
            {/* Body (open ↔ close) */}
            <View
              style={{
                position: 'absolute',
                left: cx - bodyW / 2,
                top: bodyTop,
                width: bodyW,
                height: bodyH,
                backgroundColor: color,
                borderRadius: 1,
              }}
            />
          </React.Fragment>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  yLabel: {
    position: 'absolute',
    right: 0,
    fontSize: FontSize.caption,
    color: Colors.text.muted,
    fontFamily: FontFamily.mono ?? undefined,
    fontWeight: FontWeight.medium,
  },
});
