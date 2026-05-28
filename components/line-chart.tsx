import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

import { Colors, FontFamily, FontSize, FontWeight } from '@/src/theme';

interface Props {
  data: number[];
  width: number;
  height: number;
  positive: boolean;
}

interface Segment {
  x: number;
  y: number;
  length: number;
  angle: number;
}

function buildSegments(
  data: number[],
  width: number,
  height: number
): Segment[] {
  if (data.length < 2) return [];

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pad = height * 0.1;

  const points = data.map((v, i) => ({
    x: (i / (data.length - 1)) * width,
    y: height - pad - ((v - min) / range) * (height - pad * 2),
  }));

  return points.slice(0, -1).map((p, i) => {
    const next = points[i + 1];
    const dx = next.x - p.x;
    const dy = next.y - p.y;
    const length = Math.sqrt(dx * dx + dy * dy);
    const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
    return { x: p.x, y: p.y, length, angle };
  });
}

function formatIDR(price: number): string {
  return Math.round(price)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

export function LineChart({ data, width, height, positive }: Props) {
  const color    = positive ? Colors.sentiment.positive : Colors.sentiment.negative;
  const segments = buildSegments(data, width, height);

  const min = Math.min(...data);
  const max = Math.max(...data);

  return (
    <View style={{ width, height }}>
      {/* Y-axis labels */}
      <Text style={[styles.yLabel, { top: 0 }]}>{formatIDR(max)}</Text>
      <Text style={[styles.yLabel, { bottom: 0 }]}>{formatIDR(min)}</Text>

      {/* Subtle horizontal baseline at 50% */}
      <View
        style={[
          styles.baseline,
          { top: height / 2, width },
        ]}
      />

      {/* Line segments */}
      {segments.map((seg, i) => (
        <View
          key={i}
          style={[
            styles.segment,
            {
              width:  seg.length,
              top:    seg.y - 1,
              left:   seg.x,
              backgroundColor: color,
              transform: [{ rotate: `${seg.angle}deg` }],
            },
          ]}
        />
      ))}

      {/* Last-point dot */}
      {segments.length > 0 && (() => {
        const last = data[data.length - 1];
        const min2 = Math.min(...data);
        const max2 = Math.max(...data);
        const range2 = max2 - min2 || 1;
        const pad = height * 0.1;
        const dotY = height - pad - ((last - min2) / range2) * (height - pad * 2);
        const dotX = width;
        return (
          <View
            style={[
              styles.dot,
              { top: dotY - 4, left: dotX - 4, backgroundColor: color },
            ]}
          />
        );
      })()}
    </View>
  );
}

const styles = StyleSheet.create({
  segment: {
    position: 'absolute',
    height: 2,
    borderRadius: 1,
    transformOrigin: 'left center',
  },
  dot: {
    position: 'absolute',
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  baseline: {
    position: 'absolute',
    height: 1,
    backgroundColor: Colors.border.default,
    opacity: 0.6,
  },
  yLabel: {
    position: 'absolute',
    right: 0,
    fontSize: FontSize.caption,
    color: Colors.text.muted,
    fontFamily: FontFamily.mono ?? undefined,
    fontWeight: FontWeight.medium,
  },
});
