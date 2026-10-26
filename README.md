# WindGrid DE

Day-ahead wind power forecasts for Germany's four grid zones (50Hertz, Amprion, TenneT, TransnetBW), onshore and offshore, with uncertainty bands. Every morning before the 12:00 day-ahead auction, it pulls weather forecasts at the locations of Germany's ~30,000 wind turbines, aggregates them by installed capacity, and forecasts hourly wind generation for the next day. Once the actuals come in, it compares its forecasts against the official TSO day-ahead forecasts and publishes the results.
