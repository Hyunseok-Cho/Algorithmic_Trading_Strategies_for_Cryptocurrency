import style from './TradingChart.module.scss'
import { useEffect, useRef, useState } from 'react'

export default function TradingChart() {
  const containerRef = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'
    script.async = true
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: 'BINANCE:BTCUSDT',
      interval: '60',
      timezone: 'Etc/UTC',
      theme: 'light',
      style: '1',
      locale: 'en',
      allow_symbol_change: true,
      calendar: false,
      support_host: 'https://www.tradingview.com',
    })
    script.onerror = () => setFailed(true)
    container.appendChild(script)

    return () => {
      script.onerror = null
      container.replaceChildren()
    }
  }, [])

  return (
    <section className={style.section} aria-label="Market chart">
      {failed && (
        <p role="status">The chart could not load. Please check your connection and reload.</p>
      )}
      <div className={`tradingview-widget-container ${style.chart}`} ref={containerRef} />
    </section>
  )
}
