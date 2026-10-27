import style from './PaperTrading.module.scss'
import {
  Tile,
  Table,
  TableHead,
  TableRow,
  TableHeader,
  TableBody,
  TableCell,
  TableContainer,
} from '@carbon/react'

export default function PaperTrading() {
  const initialBalance = 10000
  const trades = [
    {
      id: 5,
      closedAt: '2026-10-25 16:30',
      symbol: 'BTC/USDT',
      side: 'Long',
      quantity: 0.01,
      entry: 68000,
      exit: 69000,
    },
    {
      id: 4,
      closedAt: '2026-10-24 12:00',
      symbol: 'ETH/USDT',
      side: 'Long',
      quantity: 0.5,
      entry: 2500,
      exit: 2460,
    },
    {
      id: 3,
      closedAt: '2026-10-23 09:15',
      symbol: 'BTC/USDT',
      side: 'Long',
      quantity: 0.02,
      entry: 67000,
      exit: 68000,
    },
    {
      id: 2,
      closedAt: '2026-10-22 18:45',
      symbol: 'ETH/USDT',
      side: 'Long',
      quantity: 1,
      entry: 2400,
      exit: 2500,
    },
    {
      id: 1,
      closedAt: '2026-10-21 11:00',
      symbol: 'BTC/USDT',
      side: 'Long',
      quantity: 0.01,
      entry: 66000,
      exit: 67000,
    },
  ]
  const pnl = trades.reduce(
    (total, trade) => total + (trade.exit - trade.entry) * trade.quantity,
    0,
  )
  const money = (value: number) =>
    new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)

  return (
    <section className={style.section} aria-labelledby="paper-title">
      <h2 id="paper-title">Paper trading</h2>
      <div className={style.metrics}>
        <Tile>
          <p className={style.metricLabel}>Initial balance</p>
          <p className={style.metricValue}>{money(initialBalance)}</p>
        </Tile>
        <Tile>
          <p className={style.metricLabel}>Total balance</p>
          <p className={style.metricValue}>{money(initialBalance + pnl)}</p>
        </Tile>
        <Tile>
          <p className={style.metricLabel}>Realized PnL</p>
          <p className={style.metricValue}>{money(pnl)}</p>
        </Tile>
        <Tile>
          <p className={style.metricLabel}>Return</p>
          <p className={style.metricValue}>{((pnl / initialBalance) * 100).toFixed(2)}%</p>
        </Tile>
      </div>

      <div className={style.tableWrapper}>
        <TableContainer
          title="Recent trades"
          description="Latest 5 closed paper trades (mock data)"
        >
          <Table aria-label="Recent paper trades" size="lg">
            <TableHead>
              <TableRow>
                <TableHeader>Closed at (UTC)</TableHeader>
                <TableHeader>Symbol</TableHeader>
                <TableHeader>Side</TableHeader>
                <TableHeader>Quantity</TableHeader>
                <TableHeader>Entry price</TableHeader>
                <TableHeader>Exit price</TableHeader>
                <TableHeader>PnL</TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {trades.slice(0, 5).map((trade) => (
                <TableRow key={trade.id}>
                  <TableCell>{trade.closedAt}</TableCell>
                  <TableCell>{trade.symbol}</TableCell>
                  <TableCell>{trade.side}</TableCell>
                  <TableCell>{trade.quantity}</TableCell>
                  <TableCell>{money(trade.entry)}</TableCell>
                  <TableCell>{money(trade.exit)}</TableCell>
                  <TableCell>{money((trade.exit - trade.entry) * trade.quantity)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </div>
    </section>
  )
}
