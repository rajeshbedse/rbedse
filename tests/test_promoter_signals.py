import pandas as pd

from nse_pipeline.promoter_signals import build_promoter_signals


def test_buy_candidate_is_verified_with_sell_and_pledge(tmp_path):
    path = tmp_path / "insider.csv"
    pd.DataFrame([
        {
            "Symbol": "ABC", "Company Name": "ABC Ltd", "Category of Person": "Promoter",
            "Type of Instrument": "Equity", "Securities Acquired/Disposed (No.)": "100000",
            "Securities Acquired/Disposed (Value)": "3000000", "Transaction Type": "Buy",
            "Mode of Acquisition/Disposal": "Market Purchase",
        },
        {
            "Symbol": "ABC", "Company Name": "ABC Ltd", "Category of Person": "Promoter",
            "Type of Instrument": "Equity", "Securities Acquired/Disposed (No.)": "20000",
            "Securities Acquired/Disposed (Value)": "600000", "Transaction Type": "Sell",
            "Mode of Acquisition/Disposal": "Market Sale",
        },
        {
            "Symbol": "ABC", "Company Name": "ABC Ltd", "Category of Person": "Promoter",
            "Type of Instrument": "Equity", "Securities Acquired/Disposed (No.)": "50000",
            "Securities Acquired/Disposed (Value)": "1500000", "Transaction Type": "Other",
            "Mode of Acquisition/Disposal": "Pledge",
        },
    ]).to_csv(path, index=False)

    result = build_promoter_signals(path).set_index("Symbol")
    assert result.loc["ABC", "QualifiedBuy"] is True
    assert result.loc["ABC", "HasMarketSell"] is True
    assert result.loc["ABC", "HasPledge"] is True
    assert result.loc["ABC", "PromoterSignal"] == "BUY + SELL + PLEDGE"
    assert result.loc["ABC", "SellBuyRatioPct"] == 20.0


def test_standalone_sell_and_pledge_are_visible(tmp_path):
    path = tmp_path / "insider.csv"
    pd.DataFrame([
        {
            "Symbol": "XYZ", "Company Name": "XYZ Ltd", "Category of Person": "Promoter",
            "Type of Instrument": "Equity", "Securities Acquired/Disposed (No.)": "10000",
            "Securities Acquired/Disposed (Value)": "1000000", "Transaction Type": "Sell",
            "Mode of Acquisition/Disposal": "Market Sale",
        },
        {
            "Symbol": "PQR", "Company Name": "PQR Ltd", "Category of Person": "Promoter",
            "Type of Instrument": "Equity", "Securities Acquired/Disposed (No.)": "20000",
            "Securities Acquired/Disposed (Value)": "2000000", "Transaction Type": "Other",
            "Mode of Acquisition/Disposal": "Pledge",
        },
    ]).to_csv(path, index=False)

    result = build_promoter_signals(path).set_index("Symbol")
    assert result.loc["XYZ", "PromoterSignal"] == "STANDALONE SELL"
    assert result.loc["PQR", "PromoterSignal"] == "STANDALONE PLEDGE"
    assert result.loc["XYZ", "QualifiedBuy"] is False
    assert result.loc["PQR", "QualifiedBuy"] is False
