def moving_average(data, window_size=7):
    """
    Kukuhanin ang average ng huling 'n' periods (default is 7 days para mas accurate).
    data: listahan ng historical usage (e.g., [100, 120, 150...])
    """
    if not data:
        return 0
    
    if len(data) < window_size:
        # Kung kulang pa ang data sa window size, kunin ang average ng kung ano lang ang meron
        return round(sum(data) / len(data), 2)
    
    # Kunin ang huling data points base sa window_size
    recent_data = data[-window_size:]
    forecast = sum(recent_data) / window_size
    return round(forecast, 2)

def predict_days_left(current_stock, historical_usage, window_size=7):
    """
    Hula kung ilang araw bago ma-zero ang stock base sa burn rate.
    """
    # Kunin ang average daily usage (Burn Rate)
    daily_burn_rate = moving_average(historical_usage, window_size)
    
    if daily_burn_rate <= 0:
        return "N/A" # Hindi nagagamit ang product
    
    # Prediction: Kasalukuyang Stock / Average na nauubos kada araw
    days_left = current_stock / daily_burn_rate
    
    return round(days_left, 1) # Halimbawa: 3.5 days

def detect_trend(data):
    """
    I-compare ang average ng huling 3 araw vs 3 araw bago iyon 
    para mas accurate ang trend detection kaysa sa huling 2 records lang.
    """
    if len(data) < 6:
        # Kung konti pa ang data, fallback sa dating logic
        if len(data) < 2: return "Stable"
        return "Upward Trend" if data[-1] > data[-2] else "Downward Trend" if data[-1] < data[-2] else "Stable"
    
    recent_avg = sum(data[-3:]) / 3
    previous_avg = sum(data[-6:-3]) / 3
    
    if recent_avg > previous_avg * 1.05: # 5% threshold para hindi masyadong sensitive
        return "Upward Trend (Increasing Demand)"
    elif recent_avg < previous_avg * 0.95:
        return "Downward Trend (Decreasing Demand)"
    else:
        return "Stable"