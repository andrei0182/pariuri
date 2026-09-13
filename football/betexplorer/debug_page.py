from betscraper.driver import build_driver
import time

driver = build_driver(headless=True)
driver.get("https://www.betexplorer.com/football/results/?year=2026&month=09&day=13")
time.sleep(15)  # aceeași fereastră de timp ca WebDriverWait

with open("debug_page.html", "w", encoding="utf-8") as f:
    f.write(driver.page_source)

driver.quit()
print("Saved debug_page.html —", len(driver.page_source), "chars")