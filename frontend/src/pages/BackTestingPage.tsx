import style from './BackTestingPage.module.scss'
import TradeExecutionChart from '../components/TradeExecutionChart'
import { useEffect, useRef, useState } from 'react'
import {
  Button,
  Checkbox,
  InlineLoading,
  Select,
  SelectItem,
  Tile,
  Table,
  TableHead,
  TableRow,
  TableHeader,
  TableBody,
  TableCell,
  TableContainer,
} from '@carbon/react'
import type { FormEvent } from 'react'

const strategies = [
  { id: 'rsi-macd', name: 'RSI + MACD', color: '#0f62fe', gain: 0.12 },
  { id: 'ema', name: 'EMA Crossover', color: '#8a3ffc', gain: 0.08 },
  { id: 'bollinger', name: 'Bollinger Bands Mean Reversion', color: '#007d79', gain: 0.06 },
  { id: 'spa', name: 'Price Action — SPA (optional)', color: '#9f1853', gain: -0.03 },
]

type StrategyResult = {
  id: string
  name: string
  color: string
  equity: number[]
  tradePnls: number[]
  returnPct: number
  pnl: number
  drawdown: number
  trades: number
  frequency: number
  risk: number
  maxWin: number
  minWin: number
  maxLoss: number
  minLoss: number
  winRate: number
  averagePnl: number
}

const metricDefinitions: {
  key: keyof Pick<
    StrategyResult,
    | 'pnl'
    | 'frequency'
    | 'risk'
    | 'returnPct'
    | 'drawdown'
    | 'maxWin'
    | 'minWin'
    | 'maxLoss'
    | 'minLoss'
    | 'winRate'
    | 'averagePnl'
    | 'trades'
  >
  label: string
  unit: string
  note: string
}[] = [
  { key: 'pnl', label: 'Net PnL', unit: 'USD', note: 'Sum of closed-trade PnL; fees excluded.' },
  {
    key: 'trades',
    label: 'Closed trades',
    unit: 'trades',
    note: 'Total number of completed trades.',
  },
  {
    key: 'frequency',
    label: 'Trading frequency',
    unit: 'trades / 30 days',
    note: 'Closed trades divided by inclusive calendar days × 30.',
  },
  {
    key: 'risk',
    label: 'Risk: trade-return volatility',
    unit: '%',
    note: 'Population standard deviation of trade PnL / initial balance. Not annualized.',
  },
  {
    key: 'returnPct',
    label: 'Total return',
    unit: '%',
    note: 'Net PnL divided by initial balance × 100.',
  },
  {
    key: 'drawdown',
    label: 'Max drawdown',
    unit: '%',
    note: 'Largest peak-to-trough decline in closed-trade equity; excludes intratrade changes.',
  },
  {
    key: 'maxWin',
    label: 'Largest winning trade',
    unit: 'USD',
    note: 'Maximum positive trade PnL.',
  },
  {
    key: 'minWin',
    label: 'Smallest winning trade',
    unit: 'USD',
    note: 'Minimum positive trade PnL; zero-PnL trades excluded.',
  },
  {
    key: 'maxLoss',
    label: 'Largest losing trade',
    unit: 'USD loss',
    note: 'Largest loss magnitude, shown as a positive amount.',
  },
  {
    key: 'minLoss',
    label: 'Smallest losing trade',
    unit: 'USD loss',
    note: 'Smallest non-zero loss magnitude, shown as a positive amount.',
  },
  {
    key: 'winRate',
    label: 'Win rate',
    unit: '%',
    note: 'Winning trades divided by all closed trades × 100.',
  },
  {
    key: 'averagePnl',
    label: 'Average trade PnL',
    unit: 'USD',
    note: 'Net PnL divided by closed trades.',
  },
]

type Result = {
  config: { symbol: string; timeframe: string; start: string; end: string }
  rows: StrategyResult[]
}

export default function BackTestingPage() {
  const [symbol, setSymbol] = useState('BTCUSDT')
  const [timeframe, setTimeframe] = useState('1h')
  const [start, setStart] = useState('2021-01-01')
  const [end, setEnd] = useState('2026-10-25')
  const [selected, setSelected] = useState(strategies.map((strategy) => strategy.id))
  const [phase, setPhase] = useState<'idle' | 'fetching' | 'loading'>('idle')
  const [result, setResult] = useState<Result | null>(null)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])
  useEffect(() => () => timers.current.forEach(clearTimeout), [])
  const today = new Date().toLocaleDateString('en-CA')
  const busy = phase !== 'idle'
  const valid = selected.length > 0 && start >= '2021-01-01' && start <= end && end <= today
  const money = (value: number) =>
    new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)

  function run(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!valid || busy) return
    const config = { symbol, timeframe, start, end }
    const chosen = strategies.filter((strategy) => selected.includes(strategy.id))
    setResult(null)
    setPhase('fetching')
    timers.current = [
      setTimeout(() => setPhase('loading'), 800),
      setTimeout(() => {
        const days = (Date.parse(config.end) - Date.parse(config.start)) / 86400000 + 1
        const rows = chosen.map((strategy) => {
          const strategyIndex = strategies.findIndex((item) => item.id === strategy.id)
          const trades = 30 + strategyIndex * 12
          const rawPnls = Array.from(
            { length: trades },
            (_, index) => Math.sin(index * 1.7 + strategyIndex) * 140,
          )
          const adjustment =
            (strategy.gain * 10000 - rawPnls.reduce((sum, value) => sum + value, 0)) / trades
          const tradePnls = rawPnls.map((value) => value + adjustment)
          const equity = [10000]
          for (const value of tradePnls) equity.push(equity[equity.length - 1] + value)
          let peak = equity[0]
          let drawdown = 0
          for (const value of equity) {
            peak = Math.max(peak, value)
            drawdown = Math.max(drawdown, ((peak - value) / peak) * 100)
          }
          const pnl = equity[equity.length - 1] - 10000
          const averagePnl = pnl / trades
          const wins = tradePnls.filter((value) => value > 0)
          const losses = tradePnls.filter((value) => value < 0).map((value) => -value)
          return {
            ...strategy,
            equity,
            tradePnls,
            pnl,
            returnPct: (pnl / 10000) * 100,
            drawdown,
            trades,
            frequency: (trades / days) * 30,
            risk:
              (Math.sqrt(
                tradePnls.reduce((sum, value) => sum + (value - averagePnl) ** 2, 0) / trades,
              ) /
                10000) *
              100,
            maxWin: wins.length ? Math.max(...wins) : 0,
            minWin: wins.length ? Math.min(...wins) : 0,
            maxLoss: losses.length ? Math.max(...losses) : 0,
            minLoss: losses.length ? Math.min(...losses) : 0,
            winRate: (wins.length / trades) * 100,
            averagePnl,
          }
        })
        setResult({ config, rows })
        setPhase('idle')
      }, 1800),
    ]
  }

  function downloadCsv() {
    if (!result) return
    const lines: (string | number)[][] = [
      [
        'Record type',
        'Data type',
        'Symbol',
        'Timeframe',
        'Start',
        'End',
        'Strategy',
        'Metric',
        'Unit',
        'Value',
        'Definition',
      ],
    ]
    for (const row of result.rows) {
      const prefix = [
        'MOCK',
        result.config.symbol,
        result.config.timeframe,
        result.config.start,
        result.config.end,
        row.name,
      ]
      lines.push([
        'metric',
        ...prefix,
        'Initial balance',
        'USD',
        10000,
        'Initial equity per strategy',
      ])
      lines.push([
        'metric',
        ...prefix,
        'Final balance',
        'USD',
        row.equity[row.equity.length - 1].toFixed(6),
        'Initial balance plus net PnL',
      ])
      for (const metric of metricDefinitions)
        lines.push([
          'metric',
          ...prefix,
          metric.label,
          metric.unit,
          row[metric.key].toFixed(6),
          metric.note,
        ])
      row.equity.forEach((value, index) =>
        lines.push([
          'equity',
          ...prefix,
          `Equity point ${index}`,
          'USD',
          value.toFixed(6),
          'Synthetic points evenly spaced across selected period',
        ]),
      )
      row.tradePnls.forEach((value, index) =>
        lines.push([
          'trade',
          ...prefix,
          `Trade ${index + 1} PnL`,
          'USD',
          value.toFixed(6),
          'Synthetic closed-trade PnL; fees excluded',
        ]),
      )
    }
    const csv = lines
      .map((line) => line.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(','))
      .join('\r\n')
    const url = URL.createObjectURL(new Blob(['\uFEFF', csv], { type: 'text/csv;charset=utf-8;' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `mock-backtest-${result.config.symbol}-${result.config.start}-${result.config.end}.csv`
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <div className={style.page}>
      <h1 className={style.pageTitle}>Back Testing</h1>
      <form onSubmit={run} className={style.backtestControls}>
        <fieldset disabled={busy}>
          <legend className={style.controlHeading}>Backtest configuration</legend>
          <div className={style.filterBar}>
            <Select
              id="symbol"
              labelText="Symbol"
              value={symbol}
              onChange={(event) => setSymbol(event.target.value)}
            >
              {['BTCUSDT', 'ETHUSDT', 'SOLUSDT'].map((value) => (
                <SelectItem key={value} value={value} text={value} />
              ))}
            </Select>
            <Select
              id="timeframe"
              labelText="Timeframe"
              value={timeframe}
              onChange={(event) => setTimeframe(event.target.value)}
            >
              {['15m', '1h', '4h', '1d'].map((value) => (
                <SelectItem key={value} value={value} text={value} />
              ))}
            </Select>
            <div>
              <label className={style.dateLabel} htmlFor="start-date">
                Start date
              </label>
              <input
                className={style.dateInput}
                id="start-date"
                type="date"
                min="2021-01-01"
                max={end || today}
                required
                value={start}
                onChange={(event) => setStart(event.target.value)}
              />
            </div>
            <div>
              <label className={style.dateLabel} htmlFor="end-date">
                End date
              </label>
              <input
                className={style.dateInput}
                id="end-date"
                type="date"
                min={start || '2021-01-01'}
                max={today}
                required
                value={end}
                onChange={(event) => setEnd(event.target.value)}
              />
            </div>
          </div>
          <fieldset className={style.strategyOptions}>
            <legend className={style.controlHeading}>Strategies to compare (mock)</legend>
            {strategies.map((strategy) => (
              <Checkbox
                key={strategy.id}
                id={strategy.id}
                labelText={strategy.name}
                checked={selected.includes(strategy.id)}
                onChange={(_, { checked }) =>
                  setSelected((current) =>
                    checked
                      ? [...current, strategy.id]
                      : current.filter((id) => id !== strategy.id),
                  )
                }
              />
            ))}
          </fieldset>
        </fieldset>
        {!valid && (
          <p role="status" className={style.validation}>
            Select at least one strategy and a valid date range from 2021 onwards, ending no later
            than today.
          </p>
        )}
        <Button type="submit" disabled={busy || !valid}>
          Run backtest
        </Button>
        {busy && (
          <InlineLoading
            description={
              phase === 'fetching'
                ? 'Fetching market data… (simulated)'
                : 'Loading strategy logic… (simulated)'
            }
          />
        )}
      </form>
      {result && (
        <section className={style.results} aria-labelledby="results-title" aria-live="polite">
          <div className={style.resultsHeading}>
            <h2 id="results-title">Backtest results</h2>
            <div className={style.exportActions}>
              <Button kind="secondary" onClick={downloadCsv}>
                Export all data (CSV)
              </Button>
              <Button kind="tertiary" onClick={() => window.print()}>
                Print / Save PDF
              </Button>
            </div>
          </div>
          <p className={style.sectionDescription}>
            MOCK RESULTS · {result.config.symbol} · {result.config.timeframe} ·{' '}
            {result.config.start} to {result.config.end}. Illustrative figures only; filters do not
            drive a real simulation. Initial balance: $10,000 per strategy. Fees excluded.
          </p>
          <div className={style.metrics}>
            {result.rows.map((row) => (
              <Tile key={row.id}>
                <p className={style.metricLabel}>{row.name}</p>
                <p className={style.metricValue}>{row.returnPct.toFixed(2)}%</p>
                <p>Return · PnL {money(row.pnl)}</p>
              </Tile>
            ))}
          </div>
          <div className={style.tableWrapper}>
            <TableContainer title="Strategy comparison" description="Simulated performance metrics">
              <Table aria-label="Mock strategy comparison">
                <TableHead>
                  <TableRow>
                    {['Strategy', 'Final balance', 'PnL', 'Return', 'Max drawdown', 'Trades'].map(
                      (label) => (
                        <TableHeader key={label}>{label}</TableHeader>
                      ),
                    )}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {result.rows.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell>{row.name}</TableCell>
                      <TableCell>{money(row.equity[row.equity.length - 1])}</TableCell>
                      <TableCell>{money(row.pnl)}</TableCell>
                      <TableCell>{row.returnPct.toFixed(2)}%</TableCell>
                      <TableCell>{row.drawdown.toFixed(2)}%</TableCell>
                      <TableCell>{row.trades}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </div>
          <TradeExecutionChart
            key={result.config.symbol + result.config.start + result.config.end}
            strategies={result.rows}
            symbol={result.config.symbol}
            start={result.config.start}
            end={result.config.end}
            timeframe={result.config.timeframe}
          />
          <div className={style.equitySection}>
            <h3>Equity comparison</h3>
            <p className={style.sectionDescription}>
              Synthetic equity curves · USD · evenly spaced points across the selected period
            </p>
            <svg
              className={style.equityChart}
              viewBox="0 0 900 300"
              role="img"
              aria-label="Mock equity comparison chart. Detailed figures are in the comparison table above."
            >
              {[9000, 10000, 11000, 12000].map((value) => (
                <g key={value}>
                  <line
                    x1="65"
                    x2="880"
                    y1={260 - ((value - 9000) / 3000) * 230}
                    y2={260 - ((value - 9000) / 3000) * 230}
                    stroke="#ddd"
                  />
                  <text x="5" y={265 - ((value - 9000) / 3000) * 230} fontSize="12">
                    {value.toLocaleString('en-US')}
                  </text>
                </g>
              ))}
              {result.rows.map((row) => (
                <polyline
                  key={row.id}
                  fill="none"
                  stroke={row.color}
                  strokeWidth="2"
                  points={row.equity
                    .map(
                      (value, index) =>
                        `${65 + (index / (row.equity.length - 1)) * 815},${260 - ((value - 9000) / 3000) * 230}`,
                    )
                    .join(' ')}
                />
              ))}
              <text x="65" y="290" fontSize="12">
                {result.config.start}
              </text>
              <text x="880" y="290" textAnchor="end" fontSize="12">
                {result.config.end}
              </text>
            </svg>
            <ul className={style.chartLegend}>
              {result.rows.map((row) => (
                <li key={row.id}>
                  <span style={{ background: row.color }} />
                  {row.name}
                </li>
              ))}
            </ul>
          </div>
          <h3>Metric comparison</h3>
          <p className={style.sectionDescription}>
            Each chart uses its own unit and scale, with a zero baseline. Values are not normalized.
            Risk is defined here as trade-return volatility. Loss charts show positive loss
            magnitudes. Zero means no qualifying winning or losing trades.
          </p>
          <div className={style.metricCharts}>
            {metricDefinitions.map((metric) => {
              const values = result.rows.map((row) => row[metric.key])
              const minimum = Math.min(0, ...values)
              const maximum = Math.max(0, ...values)
              const range = maximum - minimum || 1
              const zero = (-minimum / range) * 100
              return (
                <Tile key={metric.key} className={style.metricChart}>
                  <h4>{metric.label}</h4>
                  <p className={style.metricUnit}>{metric.unit}</p>
                  <p className={style.metricNote}>{metric.note}</p>
                  <ul>
                    {result.rows.map((row) => {
                      const value = row[metric.key]
                      return (
                        <li key={row.id}>
                          <div className={style.metricRowLabel}>
                            <span>{row.name}</span>
                            <strong>
                              {value.toLocaleString('en-US', {
                                maximumFractionDigits: metric.key === 'trades' ? 0 : 2,
                              })}
                            </strong>
                          </div>
                          <div
                            className={style.metricTrack}
                            role="img"
                            aria-label={`${row.name}: ${value.toFixed(2)} ${metric.unit}`}
                          >
                            <span className={style.metricZero} style={{ left: `${zero}%` }} />
                            <span
                              className={style.metricBar}
                              style={{
                                background: row.color,
                                left: `${((Math.min(0, value) - minimum) / range) * 100}%`,
                                width: `${(Math.abs(value) / range) * 100}%`,
                              }}
                            />
                          </div>
                        </li>
                      )
                    })}
                  </ul>
                </Tile>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}
