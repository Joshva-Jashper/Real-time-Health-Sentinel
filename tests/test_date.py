from playwright.sync_api import Page,expect


def selectOption(page,isFuture,date,Month,year):
    next_ = page.locator('[data-handler="next"]')
    back_ = page.locator('[data-handler="prev"')

    

    
    while True:
        current_month = page.locator('.ui-datepicker-month').inner_text()
        current_year = page.locator(".ui-datepicker-year").inner_text()
        if current_month == Month and current_year == year:
            break
        if isFuture == True:
            next_.click()
        else:
            back_.click()

    dateButton = page.locator(".ui-datepicker-calendar tbody tr td a").all()
    for button in dateButton:
        cal = button.inner_text()
        if cal == date:
            button.click()
            break





def test_picker(page:Page):
    page.goto("https://demo.automationtesting.in/Datepicker.html")
    button = page.locator("#datepicker1")
    button.click()
    page.wait_for_timeout(5000)
    

    isFuture = True
    date = "14"
    Month = "October"
    year = "2028"

    selectOption(page,isFuture,date,Month,year);

def test_picker2(page:Page):
    page.goto("https://demo.automationtesting.in/Datepicker.html")
    click = page.locator("#datepicker2")
    click.click()
    click.first.wait_for()

    select = page.locator(".datepick-month-year[title='Change the month']")
    select.select_option(label="May")

    year = page.locator(".datepick-month-year[title='Change the year']")
    year.select_option(label="2020")

    date = "28"

    all_date=page.locator(".datepick-popup tbody tr td a")
    all_date.get_by_text(date).click()

    page.wait_for_timeout(5000)
    
