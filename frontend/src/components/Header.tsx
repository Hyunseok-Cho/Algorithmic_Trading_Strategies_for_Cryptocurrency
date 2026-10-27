import style from './Header.module.scss'
import {
  Header as CarbonHeader,
  HeaderName,
  HeaderNavigation,
  HeaderMenuItem,
  HeaderGlobalBar,
  Theme,
} from '@carbon/react'

export default function Header({ backTesting }: { backTesting: boolean }) {
  return (
    <Theme theme="g100">
      <CarbonHeader className={style.projectHeader} aria-label="Algorithmic Trading Strategies">
        <HeaderName href="#/" prefix="">
          Algorithmic Trading Strategies
        </HeaderName>
        <HeaderNavigation aria-label="Main navigation">
          <HeaderMenuItem href="#/" isCurrentPage={!backTesting}>
            Home
          </HeaderMenuItem>
          <HeaderMenuItem href="#/back-testing" isCurrentPage={backTesting}>
            Back Testing
          </HeaderMenuItem>
        </HeaderNavigation>
        <HeaderGlobalBar>
          <span className={style.mockDataStatus}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="8" cy="8" r="6.25" stroke="currentColor" strokeWidth="1.5" />
              <path d="M8 7v4M8 4.5v1" stroke="currentColor" strokeWidth="1.5" />
            </svg>
            Mock data
          </span>
          <span className={style.headerUniversity}>Silesian University of Technology</span>
        </HeaderGlobalBar>
      </CarbonHeader>
    </Theme>
  )
}
