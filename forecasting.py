from datetime import datetime

def get_seasonal_factor():
    """
    Nagbibigay ng multiplier base sa kasalukuyang buwan.
    PADECO Business Logic:
    - Oct to Dec: Peak Season (High Demand - 1.3x)
    - Jan to Feb: Lean Season (Low Demand - 0.8x)
    - Others: Normal (1.0x)
    """
    month = datetime.now().month
    if month in [10, 11, 12]:
        return 1.3
    elif month in [1, 2]:
        return 0.8
    else:
        return 1.0

def moving_average(data, window_size=7):
    if not data:
        return 0
    if len(data) < window_size:
        return sum(data) / len(data)
    recent_data = data[-window_size:]
    return sum(recent_data) / window_size

def predict_days_left(current_stock, historical_usage, weather_condition="Clear", window_size=7):
    """
    Updated AI Logic: Moving Average + Seasonal Factor + Weather Impact
    weather_condition: pwedeng 'Rain', 'Thunderstorm', 'Clear' (galing sa Weather API)
    """
    # 1. Kunin ang basic burn rate (Moving Average)
    base_burn_rate = moving_average(historical_usage, window_size)
    
    if base_burn_rate <= 0:
        return "N/A"

    # 2. I-apply ang Seasonal Factor (e.g., mas mabilis maubos pag peak season)
    seasonal_multiplier = get_seasonal_factor()
    
    # 3. I-apply ang Weather Factor
    # Halimbawa: Pag maulan, maaaring bumagal ang mixing/production ng 10% 
    # o kailangan ng mas mataas na buffer stock dahil mahirap ang delivery.
    weather_multiplier = 1.0
    if weather_condition in ['Rain', 'Thunderstorm', 'Drizzle']:
        weather_multiplier = 0.9 # Production slowdown factor
        
    # Final AI Adjusted Burn Rate
    adjusted_burn_rate = base_burn_rate * seasonal_multiplier * weather_multiplier
    
    # Prediction: Stock / Adjusted Burn Rate
    days_left = current_stock / adjusted_burn_rate
    
    return round(days_left, 1)

def detect_trend(data):
    """
    Detects if demand is increasing or decreasing based on recent activity.
    """
    if len(data) < 6:
        if len(data) < 2: return "Stable"
        return "Upward" if data[-1] > data[-2] else "Downward" if data[-1] < data[-2] else "Stable"
    
    recent_avg = sum(data[-3:]) / 3
    previous_avg = sum(data[-6:-3]) / 3
    
    if recent_avg > previous_avg * 1.05:
        return "Upward (High Demand)"
    elif recent_avg < previous_avg * 0.95:
        return "Downward (Low Demand)"
    else:
        return "Stable"