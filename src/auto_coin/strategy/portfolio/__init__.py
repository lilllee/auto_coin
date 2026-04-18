"""Portfolio-level (multi-asset) 전략 모듈.

Per-ticker `Strategy` (strategy/) 와 별도 네임스페이스.
이 패키지의 구현체는 `portfolio_runner.PortfolioSignal` 프로토콜을 따르며,
`dict[ticker, weight]` 를 반환한다.
"""
