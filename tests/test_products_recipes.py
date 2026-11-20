"""Products from screenshots and reels (with the open product databases faked), and recipes in reel notes. No network."""
import json

from test_phone_app import db_of, phone, site  # noqa: F401  (pytest fixtures)

LABEL = "Clinic Plus\nStrong & Long Shampoo\nWith Milk Protein\n340 ml"
STORE = "amazon.in/dp/B07XYZ1234\nMamaearth Onion Hair Oil for Hair Growth 250ml\n4.1 ★ 12,345 ratings\n₹ 399\nAdd to Cart\nBuy Now"
CHAT = "Bro did you see that movie yesterday?\nYeah it was great\nLet's go again on Sunday"


def test_products_are_read_from_labels_and_store_pages(phone):
    phone.open_with()
    got = phone.evaluate("t => t.map((x) => Products.pick(x))", [LABEL, STORE, CHAT, "Shampoo"])
    assert got[0] == [{"name": "Clinic Plus Strong & Long Shampoo", "brand": "Clinic Plus", "link": "", "price": ""}]
    assert got[1][0]["name"] == "Mamaearth Onion Hair Oil for Hair Growth 250ml"
    assert got[1][0]["link"] == "https://amazon.in/dp/B07XYZ1234" and got[1][0]["price"] == "₹ 399"
    assert got[2] == [] and got[3] == []  # a chat is no product, a bare word names none


def test_a_product_is_confirmed_only_when_the_database_brand_and_name_match(phone):
    phone.open_with()
    got = phone.evaluate("""async () => {
      const db = {products: []};
      Products.addFrom(db, %s, 'shot1');
      Products.addFromReel(db, {code: 'R1', caption: 'Get it here amzn.to/3abcDEF', notes: {products: ['CeraVe Foaming Cleanser']}});
      db.products.push({id: 'x', name: 'Mystery Bottle Serum', brand: '', at: 1});
      const answers = {
        'Clinic Plus Strong & Long Shampoo': {results: [{name: 'Strong & Long Shampoo', brand: 'Clinic Plus', db: 'Open Beauty Facts', quantity: '340 ml',
          url: 'https://world.openbeautyfacts.org/product/8901030865278', image: 'https://evil.example/x.jpg'}]},
        'CeraVe Foaming Cleanser': {results: [{name: 'Hydrating Cleanser', brand: 'Neutrogena', url: 'https://world.openbeautyfacts.org/product/123456'},
          {name: 'Foaming Facial Cleanser', brand: 'CeraVe', url: 'https://world.openbeautyfacts.org/product/3337875597197', db: 'Open Beauty Facts'}]},
        'Mystery Bottle Serum': {results: [{name: 'Bottle Serum', brand: 'Someone Else', url: 'https://world.openbeautyfacts.org/product/999999'}]}};
      const n = await Products.checkOnline(db, async (t) => JSON.stringify(answers[t] || {results: []}), {gap: 0});
      return [n, db.products.map((p) => [p.name, p.link || '', p.online.found, p.online.brand || '', p.online.image || ''])];
    }""" % json.dumps(LABEL))
    assert got[0] == 2
    rows = {r[0]: r[1:] for r in got[1]}
    assert rows["Clinic Plus Strong & Long Shampoo"] == ["", True, "Clinic Plus", ""]  # an image from elsewhere is dropped
    assert rows["CeraVe Foaming Cleanser"] == ["https://amzn.to/3abcDEF", True, "CeraVe", ""]  # the one that fits, not the first
    assert rows["Mystery Bottle Serum"] == ["", False, "", ""]


def test_products_have_their_own_chip_with_links(phone):
    db = {"reels": [], "inbox": [], "products": [
        {"id": "p1", "name": "Clinic Plus Strong & Long Shampoo", "brand": "Clinic Plus", "link": "", "price": "", "from": "screenshot", "at": 5,
         "online": {"found": True, "name": "Strong & Long Shampoo", "brand": "Clinic Plus", "db": "Open Beauty Facts", "quantity": "340 ml",
                    "url": "https://world.openbeautyfacts.org/product/8901030865278", "at": 6}},
        {"id": "p2", "name": "Mamaearth Onion Hair Oil", "link": "https://amazon.in/dp/B07XYZ1234", "price": "₹ 399", "from": "screenshot", "at": 4,
         "online": {"found": False, "at": 6}}]}
    phone.open_with({"db": json.dumps(db)}, "#/")
    phone.locator("[data-kind=products]").click()
    phone.get_by_text("Confirmed: Open Beauty Facts").wait_for()
    phone.get_by_text("Not found online").wait_for()
    phone.get_by_role("button", name="Product link").click()
    phone.get_by_role("button", name="Details").click()
    assert phone.rn()["opened"] == ["https://amazon.in/dp/B07XYZ1234", "https://world.openbeautyfacts.org/product/8901030865278"]
    assert phone.locator("[data-url^='https://www.google.com/search?tbm=shop&q=Clinic']").count() == 1


def test_a_cooking_reel_keeps_its_recipe_backed_by_what_is_said(phone):
    phone.open_with()
    answer = """TOPIC: Crispy rice in 10 minutes
POINTS:
1. Use day-old rice for crispy rice
INGREDIENTS:
- 2 cups day-old rice
- 1 tbsp soy sauce
- Saffron threads
STEPS:
1. Heat the pan until very hot
2. Add the rice and press it flat
3. Finish with soy sauce and garlic
TOOLS: none
PRODUCTS: none
TAKEAWAY: Dry rice gets crispy
TAGS: cooking, rice"""
    reel = {"transcript": "today we make crispy rice with day old rice and a hot pan, press the rice flat, then add soy sauce and garlic"}
    got = phone.evaluate("""([a, r]) => { const n = Notes.parse(a); const left = Notes.keepBacked(n, r);
      return [left, n.ingredients, n.steps, 'products' in n, Notes.parse(Notes.format(n)).steps]; }""", [answer, reel])
    assert got[0] == 1  # saffron is never said
    assert got[1] == ["2 cups day-old rice", "1 tbsp soy sauce"]
    assert got[2] == ["Heat the pan until very hot", "Add the rice and press it flat", "Finish with soy sauce and garlic"]
    assert got[3] is False and got[4] == got[2]
