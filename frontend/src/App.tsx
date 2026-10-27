import style from './App.module.scss'
import { useEffect, useState } from 'react'
import Header from './components/Header'
import Footer from './components/Footer'
import HomePage from './pages/HomePage'
import BackTestingPage from './pages/BackTestingPage'

export default function App() {
  const [page, setPage] = useState(window.location.hash)
  useEffect(() => {
    const navigate = () => setPage(window.location.hash)
    window.addEventListener('hashchange', navigate)
    return () => window.removeEventListener('hashchange', navigate)
  }, [])
  const backTesting = page === '#/back-testing'
  return (
    <>
      <Header backTesting={backTesting} />
      <main className={style.content}>{backTesting ? <BackTestingPage /> : <HomePage />}</main>
      <Footer />
    </>
  )
}
