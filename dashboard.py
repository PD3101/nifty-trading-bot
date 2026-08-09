"""
Interactive Dashboard
Visualizes backtest results, performance metrics, and trade analysis
Built with Streamlit
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import sys

from backtester import Backtester
import config


def create_equity_curve(trades):
    """
    Create equity curve chart

    Args:
        trades (list): List of Trade objects

    Returns:
        plotly.graph_objects.Figure
    """
    if not trades:
        return None

    # Calculate cumulative P&L
    equity_data = []
    cumulative_pnl = 0

    for trade in trades:
        cumulative_pnl += trade.pnl
        equity_data.append({
            'timestamp': trade.exit_time,
            'cumulative_pnl': cumulative_pnl,
            'trade_pnl': trade.pnl
        })

    df = pd.DataFrame(equity_data)

    # Create figure
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df['timestamp'],
        y=df['cumulative_pnl'],
        mode='lines',
        name='Equity Curve',
        line=dict(color='#00D9FF', width=2),
        fill='tozeroy',
        fillcolor='rgba(0, 217, 255, 0.1)'
    ))

    fig.update_layout(
        title='Equity Curve',
        xaxis_title='Date',
        yaxis_title='Cumulative P&L (₹)',
        hovermode='x unified',
        template='plotly_dark',
        height=400
    )

    return fig


def create_pnl_distribution(trades):
    """
    Create P&L distribution histogram

    Args:
        trades (list): List of Trade objects

    Returns:
        plotly.graph_objects.Figure
    """
    if not trades:
        return None

    pnl_values = [trade.pnl for trade in trades]

    fig = go.Figure()

    fig.add_trace(go.Histogram(
        x=pnl_values,
        nbinsx=30,
        marker=dict(
            color=pnl_values,
            colorscale='RdYlGn',
            line=dict(color='white', width=1)
        ),
        name='P&L Distribution'
    ))

    fig.update_layout(
        title='P&L Distribution',
        xaxis_title='P&L (₹)',
        yaxis_title='Frequency',
        template='plotly_dark',
        height=400
    )

    return fig


def create_win_rate_chart(results):
    """
    Create win rate comparison chart

    Args:
        results (dict): Backtest results

    Returns:
        plotly.graph_objects.Figure
    """
    categories = ['Overall', 'CALL', 'PUT']
    win_rates = [
        results['win_rate'],
        results['call_win_rate'],
        results['put_win_rate']
    ]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=categories,
        y=win_rates,
        text=[f"{wr:.1f}%" for wr in win_rates],
        textposition='auto',
        marker=dict(
            color=win_rates,
            colorscale='RdYlGn',
            cmin=0,
            cmax=100
        )
    ))

    fig.update_layout(
        title='Win Rate Analysis',
        yaxis_title='Win Rate (%)',
        yaxis=dict(range=[0, 100]),
        template='plotly_dark',
        height=400
    )

    return fig


def create_trades_over_time(trades):
    """
    Create trades over time chart

    Args:
        trades (list): List of Trade objects

    Returns:
        plotly.graph_objects.Figure
    """
    if not trades:
        return None

    # Prepare data
    trade_data = []
    for trade in trades:
        trade_data.append({
            'timestamp': trade.entry_time,
            'type': 'CALL' if trade.signal['type'] == 'BUY_CALL' else 'PUT',
            'result': 'Win' if trade.pnl > 0 else 'Loss',
            'pnl': trade.pnl
        })

    df = pd.DataFrame(trade_data)

    # Count trades per day
    df['date'] = df['timestamp'].dt.date
    daily_trades = df.groupby(['date', 'result']).size().reset_index(name='count')

    fig = go.Figure()

    for result in ['Win', 'Loss']:
        data = daily_trades[daily_trades['result'] == result]
        fig.add_trace(go.Bar(
            x=data['date'],
            y=data['count'],
            name=result,
            marker_color='#00D9FF' if result == 'Win' else '#FF4444'
        ))

    fig.update_layout(
        title='Trades Over Time',
        xaxis_title='Date',
        yaxis_title='Number of Trades',
        barmode='stack',
        template='plotly_dark',
        height=400
    )

    return fig


def create_confidence_analysis(trades):
    """
    Create confidence vs outcome analysis

    Args:
        trades (list): List of Trade objects

    Returns:
        plotly.graph_objects.Figure
    """
    if not trades:
        return None

    # Prepare data
    trade_data = []
    for trade in trades:
        trade_data.append({
            'confidence': trade.signal['confidence'],
            'pnl_percent': trade.pnl_percent,
            'result': 'Win' if trade.pnl > 0 else 'Loss',
            'type': trade.signal['type']
        })

    df = pd.DataFrame(trade_data)

    fig = px.scatter(
        df,
        x='confidence',
        y='pnl_percent',
        color='result',
        symbol='type',
        color_discrete_map={'Win': '#00D9FF', 'Loss': '#FF4444'},
        title='Confidence vs P&L%',
        labels={'confidence': 'Confidence Score', 'pnl_percent': 'P&L %'}
    )

    fig.update_layout(
        template='plotly_dark',
        height=400
    )

    return fig


def display_trade_table(trades):
    """
    Display trades as a table

    Args:
        trades (list): List of Trade objects
    """
    trade_data = []

    for i, trade in enumerate(trades, 1):
        trade_data.append({
            '#': i,
            'Type': trade.signal['type'],
            'Strike': trade.signal['strike_label'],
            'Entry Time': trade.entry_time.strftime('%Y-%m-%d %H:%M'),
            'Exit Time': trade.exit_time.strftime('%Y-%m-%d %H:%M'),
            'Entry Price': f"₹{trade.entry_price:.2f}",
            'Exit Price': f"₹{trade.exit_price:.2f}",
            'P&L': f"₹{trade.pnl:.2f}",
            'P&L %': f"{trade.pnl_percent:.2f}%",
            'Exit Reason': trade.exit_reason,
            'Confidence': f"{trade.signal['confidence']}%"
        })

    df = pd.DataFrame(trade_data)

    # Style the dataframe
    def highlight_pnl(row):
        if '₹-' in row['P&L']:
            return ['background-color: rgba(255, 68, 68, 0.2)'] * len(row)
        else:
            return ['background-color: rgba(0, 217, 255, 0.2)'] * len(row)

    styled_df = df.style.apply(highlight_pnl, axis=1)

    st.dataframe(styled_df, use_container_width=True, height=400)


def main():
    """
    Main dashboard function
    """
    st.set_page_config(
        page_title="NIFTY Options Backtester",
        page_icon="📊",
        layout="wide"
    )

    st.title("📊 NIFTY Options Trading System - Backtest Results")
    st.markdown("---")

    # Sidebar configuration
    st.sidebar.header("⚙️ Backtest Configuration")

    start_date = st.sidebar.date_input(
        "Start Date",
        value=datetime.strptime(config.BACKTEST_START_DATE, "%Y-%m-%d")
    )

    end_date = st.sidebar.date_input(
        "End Date",
        value=datetime.strptime(config.BACKTEST_END_DATE, "%Y-%m-%d")
    )

    capital_per_trade = st.sidebar.number_input(
        "Capital Per Trade (₹)",
        value=config.CAPITAL_PER_TRADE,
        min_value=10000,
        max_value=10000000,
        step=10000
    )

    run_backtest = st.sidebar.button("🚀 Run Backtest", type="primary")

    # Run backtest
    if run_backtest or 'results' not in st.session_state:
        with st.spinner("Running backtest..."):
            backtester = Backtester(
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d")
            )

            results = backtester.run_backtest()

            if results:
                st.session_state.results = results
                st.session_state.trades = results['trades']
                st.success("✓ Backtest completed!")
            else:
                st.error("✗ Backtest failed. Check data availability.")
                return

    # Display results
    if 'results' in st.session_state:
        results = st.session_state.results
        trades = st.session_state.trades

        # Key Metrics
        st.header("📈 Key Performance Metrics")

        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            st.metric("Total Trades", results['total_trades'])

        with col2:
            st.metric("Win Rate", f"{results['win_rate']:.2f}%")

        with col3:
            pnl = results['total_pnl']
            st.metric("Total P&L", f"₹{pnl:,.2f}", delta=f"{pnl:,.2f}")

        with col4:
            st.metric("Avg Win", f"₹{results['avg_win']:,.2f}")

        with col5:
            st.metric("Avg Loss", f"₹{results['avg_loss']:,.2f}")

        st.markdown("---")

        # Charts
        col1, col2 = st.columns(2)

        with col1:
            st.plotly_chart(create_equity_curve(trades), use_container_width=True)

        with col2:
            st.plotly_chart(create_win_rate_chart(results), use_container_width=True)

        col1, col2 = st.columns(2)

        with col1:
            st.plotly_chart(create_pnl_distribution(trades), use_container_width=True)

        with col2:
            st.plotly_chart(create_trades_over_time(trades), use_container_width=True)

        st.plotly_chart(create_confidence_analysis(trades), use_container_width=True)

        st.markdown("---")

        # Trade Analysis
        st.header("📊 Trade Analysis")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("CALL Trades")
            st.metric("Total CALL Trades", results['call_trades'])
            st.metric("CALL Win Rate", f"{results['call_win_rate']:.2f}%")

        with col2:
            st.subheader("PUT Trades")
            st.metric("Total PUT Trades", results['put_trades'])
            st.metric("PUT Win Rate", f"{results['put_win_rate']:.2f}%")

        st.markdown("---")

        # Trade Log
        st.header("📋 Trade Log")
        display_trade_table(trades)

        # Download Results
        st.markdown("---")
        st.header("💾 Export Results")

        # Prepare CSV
        trade_df = pd.DataFrame([{
            'Entry Time': t.entry_time,
            'Exit Time': t.exit_time,
            'Type': t.signal['type'],
            'Strike': t.signal['strike_label'],
            'Spot Price': t.signal['spot_price'],
            'Entry Price': t.entry_price,
            'Exit Price': t.exit_price,
            'Stoploss': t.stoploss_premium,
            'Target 1:1': t.target_1_1,
            'Target 1:2': t.target_1_2,
            'P&L': t.pnl,
            'P&L %': t.pnl_percent,
            'Exit Reason': t.exit_reason,
            'Confidence': t.signal['confidence'],
        } for t in trades])

        csv = trade_df.to_csv(index=False)

        st.download_button(
            label="📥 Download Trade Log (CSV)",
            data=csv,
            file_name=f"nifty_backtest_{start_date}_{end_date}.csv",
            mime="text/csv"
        )

    else:
        st.info("👈 Configure parameters and click 'Run Backtest' to start")

        # Display strategy rules
        st.header("📖 Strategy Rules")

        st.markdown("""
        ### Chart & Indicators
        - **Chart:** NIFTY FUT, 3-minute timeframe
        - **Indicators:** VWAP + VWMA-20 + Supertrend (all on FUT 3m)

        ### Entry Rules (3 Minutes)
        **BUY CALL:** Price ABOVE VWAP, VWMA-20, AND Supertrend (green)
        - Pullback to VWMA-20 detected, then bounce
        - Not chasing (4+ consecutive candles already up)

        **BUY PUT:** Price BELOW VWAP, VWMA-20, AND Supertrend (red)
        - Pullback to VWMA-20 detected, then rejection
        - Not chasing (4+ consecutive candles already down)

        ### Exit Rules
        **Stop Loss:** Supertrend LEVEL of entry candle
        **Target:** 1:2 Risk-Reward ratio
        **Hybrid:** Book 50% at 1:1, trail remaining for 1:2+

        ### Risk Management
        - Max 2-3 trades/day | Max 1-2 losses → STOP
        - Lunch hours 12:30–2:00 PM avoided
        - Strike: 1 strike ITM (50 pts) from SPOT
        """)


if __name__ == "__main__":
    main()
