import style from './TradeExecutionChart.module.scss'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Checkbox, Select, SelectItem } from '@carbon/react'
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
} from 'lightweight-charts'
import type { IChartApi, LogicalRange, SeriesMarker, Time, UTCTimestamp } from 'lightweight-charts'

type Props = {
  strategies: { id: string; name: string; tradePnls: number[] }[]
  symbol: string
  start: string
  end: string
  timeframe: string
}

export default function TradeExecutionChart({ strategies, symbol, start, end, timeframe }: Props) {
  const [strategyId, setStrategyId] = useState(strategies[0].id)
  const [indicators, setIndicators] = useState(['ema'])
  const [indicatorMenu, setIndicatorMenu] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const legendRef = useRef<HTMLDivElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const rangeRef = useRef<LogicalRange | null>(null)
  const strategy = strategies.find((item) => item.id === strategyId) ?? strategies[0]

  const data = useMemo(() => {
    const interval =
      ({ '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400 } as Record<string, number>)[timeframe] ??
      3600
    const from = Date.parse(start + 'T00:00:00Z') / 1000
    const until = Date.parse(end + 'T00:00:00Z') / 1000 + 86400
    const count = Math.ceil((until - from) / interval)
    const price = (i: number) =>
      1000 + Math.sin(i * 0.33) * 40 + Math.sin(i * 0.11) * 65 + Math.sqrt(i + 1) * 2
    const all = Array.from({ length: count + 60 }, (_, index) => {
      const open = price(Math.max(0, index - 1))
      const close = price(index)
      return {
        time: (from + (index - 60) * interval) as UTCTimestamp,
        open,
        high: Math.max(open, close) + 8,
        low: Math.min(open, close) - 8,
        close,
      }
    })
    const closes = all.map((bar) => bar.close)
    const ema = (period: number, input = closes) => {
      const values = [input[0]]
      const alpha = 2 / (period + 1)
      for (let i = 1; i < input.length; i++)
        values.push(input[i] * alpha + values[i - 1] * (1 - alpha))
      return values
    }
    const fast = ema(12)
    const slow = ema(26)
    const macd = fast.map((value, index) => value - slow[index])
    const signal = ema(9, macd)
    const rsi = Array<number>(14).fill(50)
    let gain = 0
    let loss = 0
    for (let i = 1; i <= 14; i++) {
      const change = closes[i] - closes[i - 1]
      gain += Math.max(0, change) / 14
      loss += Math.max(0, -change) / 14
    }
    for (let i = 14; i < all.length; i++) {
      if (i > 14) {
        const change = closes[i] - closes[i - 1]
        gain = (gain * 13 + Math.max(0, change)) / 14
        loss = (loss * 13 + Math.max(0, -change)) / 14
      }
      rsi.push(gain + loss === 0 ? 50 : loss === 0 ? 100 : 100 - 100 / (1 + gain / loss))
    }
    const bands = closes.map((_, index) => {
      const window = closes.slice(Math.max(0, index - 19), index + 1)
      const mean = window.reduce((sum, value) => sum + value, 0) / window.length
      const sd = Math.sqrt(
        window.reduce((sum, value) => sum + (value - mean) ** 2, 0) / window.length,
      )
      return { middle: mean, upper: mean + sd * 2, lower: mean - sd * 2 }
    })
    return all.slice(60).map((bar, index) => ({
      ...bar,
      fast: fast[index + 60],
      slow: slow[index + 60],
      rsi: rsi[index + 60],
      macd: macd[index + 60],
      signal: signal[index + 60],
      ...bands[index + 60],
    }))
  }, [start, end, timeframe])

  const fills = useMemo(
    () =>
      strategy.tradePnls
        .flatMap((pnl, index) => {
          const entry = Math.min(
            data.length - 1,
            Math.floor((index / strategy.tradePnls.length) * data.length),
          )
          const exit = Math.min(
            data.length - 1,
            entry + Math.max(1, Math.floor(data.length / strategy.tradePnls.length / 2)),
          )
          const delta = data[exit].close - data[entry].close
          const side = pnl * delta >= 0 ? 'Long' : 'Short'
          return [
            { time: data[entry].time, text: `${side} #${index + 1}`, side, pnl, kind: 'entry' },
            { time: data[exit].time, text: `Exit #${index + 1}`, side, pnl, kind: 'exit' },
          ]
        })
        .sort((a, b) => a.time - b.time),
    [data, strategy],
  )

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#ffffff' },
        textColor: '#525252',
        attributionLogo: true,
        panes: { separatorColor: '#e0e0e0', enableResize: true },
      },
      grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: {
        timeVisible: timeframe !== '1d',
        secondsVisible: false,
        borderColor: '#d0d0d0',
        minBarSpacing: 0.001,
      },
      rightPriceScale: { borderColor: '#d0d0d0' },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
      localization: {
        locale: 'en-US',
        timeFormatter: (time: Time) =>
          new Date(Number(time) * 1000).toISOString().replace('T', ' ').slice(0, 16) + ' UTC',
      },
    })
    chartRef.current = chart
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: '#089981',
      downColor: '#f23645',
      wickUpColor: '#089981',
      wickDownColor: '#f23645',
      borderVisible: false,
    })
    candles.setData(data)
    const markers: SeriesMarker<Time>[] = fills.map((fill) => ({
      time: fill.time,
      position: fill.kind === 'exit' || fill.side === 'Short' ? 'aboveBar' : 'belowBar',
      color: fill.kind === 'exit' ? '#b28600' : fill.side === 'Long' ? '#089981' : '#8a3ffc',
      shape: fill.kind === 'exit' ? 'circle' : fill.side === 'Long' ? 'arrowUp' : 'arrowDown',
      text: fill.text,
    }))
    createSeriesMarkers(candles, markers)
    const line = (
      key: 'fast' | 'slow' | 'upper' | 'middle' | 'lower' | 'rsi' | 'macd' | 'signal',
      title: string,
      color: string,
      pane = 0,
    ) => {
      const series = chart.addSeries(
        LineSeries,
        { title, color, lineWidth: 1, priceLineVisible: false, lastValueVisible: true },
        pane,
      )
      series.setData(data.map((bar) => ({ time: bar.time, value: bar[key] })))
      return series
    }
    if (indicators.includes('ema')) {
      line('fast', 'EMA 12', '#2962ff')
      line('slow', 'EMA 26', '#9c27b0')
    }
    if (indicators.includes('bands')) {
      line('upper', 'BB upper', '#787b86')
      line('middle', 'BB basis', '#2962ff')
      line('lower', 'BB lower', '#787b86')
    }
    let pane = 1
    if (indicators.includes('rsi')) {
      const series = line('rsi', 'RSI 14', '#7e57c2', pane++)
      for (const price of [30, 70])
        series.createPriceLine({
          price,
          color: '#aaa',
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: '',
        })
      series.applyOptions({
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
      })
    }
    if (indicators.includes('macd')) {
      line('macd', 'MACD', '#2962ff', pane)
      line('signal', 'Signal 9', '#ff6d00', pane)
      const histogram = chart.addSeries(
        HistogramSeries,
        { title: 'Histogram', priceLineVisible: false },
        pane,
      )
      histogram.setData(
        data.map((bar) => ({
          time: bar.time,
          value: bar.macd - bar.signal,
          color: bar.macd >= bar.signal ? '#26a69a' : '#ef5350',
        })),
      )
    }
    chart.panes().forEach((item, index) => item.setStretchFactor(index === 0 ? 3 : 1))
    const barsByTime = new Map(data.map((bar) => [bar.time as number, bar]))
    const fillsByTime = new Map<number, typeof fills>()
    for (const fill of fills)
      fillsByTime.set(fill.time, [...(fillsByTime.get(fill.time) ?? []), fill])
    chart.subscribeCrosshairMove((param) => {
      const bar = barsByTime.get(Number(param.time))
      if (legendRef.current)
        legendRef.current.textContent = bar
          ? `${symbol} · ${timeframe} · O ${bar.open.toFixed(2)} H ${bar.high.toFixed(2)} L ${bar.low.toFixed(2)} C ${bar.close.toFixed(2)}${indicators.includes('ema') ? ` · EMA 12 ${bar.fast.toFixed(2)} / 26 ${bar.slow.toFixed(2)}` : ''}${indicators.includes('rsi') ? ` · RSI ${bar.rsi.toFixed(2)}` : ''}${indicators.includes('macd') ? ` · MACD ${bar.macd.toFixed(2)} / Signal ${bar.signal.toFixed(2)}` : ''}`
          : `${symbol} · ${timeframe} · ${strategy.name}`
      const active = fillsByTime.get(Number(param.time))
      if (tooltipRef.current) {
        tooltipRef.current.hidden = !active?.length
        tooltipRef.current.textContent =
          active
            ?.map(
              (fill) =>
                `${fill.text} · ${fill.side} · $${bar?.close.toFixed(2)}${fill.kind === 'exit' ? ` · PnL $${fill.pnl.toFixed(2)}` : ''}`,
            )
            .join(' | ') ?? ''
      }
    })
    if (rangeRef.current) chart.timeScale().setVisibleLogicalRange(rangeRef.current)
    else chart.timeScale().fitContent()
    return () => {
      rangeRef.current = chart.timeScale().getVisibleLogicalRange()
      chart.remove()
      chartRef.current = null
    }
  }, [data, fills, indicators, symbol, timeframe, strategy.name])

  function exportChart() {
    const rows = [
      [
        'Data type',
        'Symbol',
        'Strategy',
        'Time (UTC)',
        'Open',
        'High',
        'Low',
        'Close',
        'EMA12',
        'EMA26',
        'RSI14',
        'MACD',
        'Signal9',
        'BB upper20',
        'BB lower20',
        'Fills',
      ],
    ]
    const fillMap = new Map<number, string[]>()
    fills.forEach((fill) =>
      fillMap.set(fill.time, [
        ...(fillMap.get(fill.time) ?? []),
        `${fill.text}: ${fill.side}${fill.kind === 'exit' ? ` PnL ${fill.pnl}` : ''}`,
      ]),
    )
    data.forEach((bar) =>
      rows.push([
        'MOCK',
        symbol,
        strategy.name,
        new Date(bar.time * 1000).toISOString(),
        ...[
          bar.open,
          bar.high,
          bar.low,
          bar.close,
          bar.fast,
          bar.slow,
          bar.rsi,
          bar.macd,
          bar.signal,
          bar.upper,
          bar.lower,
        ].map((value) => value.toFixed(6)),
        (fillMap.get(bar.time) ?? []).join('; '),
      ]),
    )
    const csv = rows
      .map((row) => row.map((value) => `"${value.replaceAll('"', '""')}"`).join(','))
      .join('\r\n')
    const url = URL.createObjectURL(new Blob(['\uFEFF', csv], { type: 'text/csv;charset=utf-8;' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `mock-chart-${symbol}-${strategy.id}.csv`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <section className={style.tradeExecution} aria-labelledby="execution-title">
      <h3 id="execution-title">Trade execution chart</h3>
      <div className={style.tradingWorkspace}>
        <div className={style.chartToolbar}>
          <Select
            id="chart-strategy"
            labelText="Strategy"
            size="sm"
            value={strategy.id}
            onChange={(event) => setStrategyId(event.target.value)}
          >
            {strategies.map((item) => (
              <SelectItem key={item.id} value={item.id} text={item.name} />
            ))}
          </Select>
          <div className={style.indicatorPicker}>
            <Button
              size="sm"
              kind="tertiary"
              aria-expanded={indicatorMenu}
              aria-controls="chart-indicators"
              onClick={() => setIndicatorMenu((open) => !open)}
            >
              Indicators
            </Button>
            {indicatorMenu && (
              <fieldset id="chart-indicators" className={style.indicatorPopover}>
                <legend>Indicators</legend>
                {[
                  { id: 'ema', name: 'EMA (12, 26)' },
                  { id: 'bands', name: 'Bollinger Bands (20, 2)' },
                  { id: 'rsi', name: 'RSI (14)' },
                  { id: 'macd', name: 'MACD (12, 26, 9)' },
                ].map((item) => (
                  <Checkbox
                    key={item.id}
                    id={`indicator-${item.id}`}
                    labelText={item.name}
                    checked={indicators.includes(item.id)}
                    onChange={(_, { checked }) =>
                      setIndicators((current) =>
                        checked ? [...current, item.id] : current.filter((id) => id !== item.id),
                      )
                    }
                  />
                ))}
                <Button size="sm" kind="ghost" onClick={() => setIndicatorMenu(false)}>
                  Done
                </Button>
              </fieldset>
            )}
          </div>
          <Button size="sm" kind="ghost" onClick={() => chartRef.current?.timeScale().fitContent()}>
            Full period
          </Button>
          <Button
            size="sm"
            kind="ghost"
            onClick={() =>
              chartRef.current?.timeScale().setVisibleLogicalRange({
                from: Math.max(0, data.length - 100),
                to: data.length - 1,
              })
            }
          >
            Latest
          </Button>
          <Button size="sm" kind="ghost" onClick={exportChart}>
            Export chart CSV
          </Button>
        </div>
        <div className={style.chartContext}>
          <strong>
            {symbol} · {timeframe}
          </strong>
          <span>
            {start} — {end} UTC
          </span>
          <span className={style.mockChartBadge}>MOCK · Synthetic prices and fills</span>
        </div>
        <div className={style.chartLiveLegend} ref={legendRef}>
          {symbol} · {timeframe} · {strategy.name}
        </div>
        <div
          className={style.interactiveChart}
          ref={containerRef}
          style={{
            height:
              460 +
              (indicators.includes('rsi') ? 160 : 0) +
              (indicators.includes('macd') ? 160 : 0),
          }}
          role="region"
          aria-label="Interactive candlestick chart. Mouse wheel to zoom, drag to scroll. Long, Short and Exit markers show mock trades."
        />
        <div ref={tooltipRef} className={style.chartFillTooltip} hidden />
        <div className={style.chartStatus}>
          <span>Wheel to zoom · Drag to pan · Hover for prices, indicators and fills</span>
          <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">
            Charts by TradingView Lightweight Charts™
          </a>
        </div>
      </div>
    </section>
  )
}
