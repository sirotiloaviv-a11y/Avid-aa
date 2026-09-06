"""Design system, escaping, charts and analytics (29, 31, 34, 35)."""

from __future__ import annotations

from .helpers import AppTestCase

from fitness_platform.db.repositories import insights
from fitness_platform.db.seed import seed
from fitness_platform.services import analytics
from fitness_platform.web.ui import components, charts
from fitness_platform.web.ui.icons import FLIPPED, icon
from fitness_platform.web.ui.primitives import attrs, classes, esc, money


class EscapingTest(AppTestCase):
    def test_text_is_escaped(self):
        self.assertEqual(esc('<script>alert("x")</script>'), "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;")

    def test_attributes_are_escaped(self):
        self.assertIn("&quot;", attrs({"title": 'a"b'}))

    def test_boolean_attributes(self):
        self.assertIn(" disabled", attrs({"disabled": True}))
        self.assertNotIn("hidden", attrs({"hidden": False}))

    def test_class_helper_drops_falsy(self):
        self.assertEqual(classes("a", "", None, {"b": True, "c": False}), "a b")

    def test_hostile_content_cannot_break_out_of_a_card(self):
        markup = components.video_card(
            video_id=1, title='<img src=x onerror="alert(1)">', duration=10,
            difficulty_label="מתחילים", category_label="ליבה", href="/x",
        )
        # The payload survives as inert text: no live tag, and the quotes that
        # would have closed the attribute are entities.
        self.assertNotIn("<img", markup)
        self.assertIn("&lt;img", markup)
        self.assertIn("&quot;alert(1)&quot;", markup)

    def test_user_supplied_text_is_escaped_in_the_page(self):
        seed()
        client = self.new_client()
        client.login("admin@example.com", "Aa123456")
        client.post(
            "/admin/videos",
            {"title": '<b>bold</b>', "duration": "10", "difficulty": "beginner",
             "category": "core", "gender_path": "female", "published": "1"},
        )
        page = client.get("/admin/videos")
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", page.text)
        self.assertNotIn("<b>bold</b>", page.text)


class ComponentTest(AppTestCase):
    def test_button_renders_as_a_link_when_given_href(self):
        self.assertIn('<a class="btn', components.button("שלח", href="/x"))
        self.assertIn("<button", components.button("שלח"))

    def test_progress_values_are_clamped(self):
        self.assertIn('aria-valuenow="100"', components.progress_bar(150))
        self.assertIn('aria-valuenow="0"', components.progress_bar(-20))

    def test_progress_ring_reports_its_value(self):
        self.assertIn("57%", components.progress_ring(57, caption="השבוע"))

    def test_table_falls_back_to_an_empty_state(self):
        self.assertIn("empty-state", components.table(["a"], []))
        self.assertIn("<table", components.table(["a"], [["1"]]))

    def test_avatar_uses_initials_without_an_image(self):
        self.assertIn(">נכ<", components.avatar("נועה כהן"))

    def test_media_placeholder_is_deterministic(self):
        self.assertEqual(components.media(seed="video-7"), components.media(seed="video-7"))

    def test_money_formatting(self):
        self.assertEqual(money(14900), "₪149")
        self.assertEqual(money(119000), "₪1,190")


class IconTest(AppTestCase):
    def test_directional_icons_flip_in_rtl(self):
        self.assertIn("icon-flip", icon("arrow"))

    def test_a_play_triangle_does_not_flip(self):
        self.assertNotIn("icon-flip", icon("play"))
        self.assertNotIn("play", FLIPPED)

    def test_unknown_icon_renders_nothing(self):
        self.assertEqual(icon("unicorn"), "")

    def test_icons_are_hidden_from_screen_readers(self):
        self.assertIn('aria-hidden="true"', icon("dashboard"))


class ChartTest(AppTestCase):
    def test_line_chart_handles_no_data(self):
        self.assertIn("chart-empty", charts.line_chart([], []))

    def test_line_chart_draws_one_path_per_series(self):
        markup = charts.line_chart(
            [
                {"name": "נשים", "values": [1, 4, 2], "tone": "female"},
                {"name": "גברים", "values": [2, 3, 5], "tone": "male"},
            ],
            ["1", "2", "3"],
        )
        self.assertEqual(markup.count("chart-line"), 2)
        self.assertIn("chart-tone-female", markup)

    def test_single_point_series_skips_the_area(self):
        markup = charts.line_chart([{"name": "x", "values": [3], "tone": "brand"}], ["1"])
        self.assertNotIn("chart-area", markup)

    def test_donut_percentages_sum_to_the_whole(self):
        markup = charts.donut_chart(
            [{"label": "נשים", "value": 62, "tone": "female"}, {"label": "גברים", "value": 38, "tone": "male"}],
            center_value="100",
        )
        self.assertIn("62%", markup)
        self.assertIn("38%", markup)

    def test_donut_handles_an_empty_dataset(self):
        self.assertIn("chart-empty", charts.donut_chart([]))

    def test_bar_chart_scales_to_the_maximum(self):
        markup = charts.bar_chart([{"label": "א", "value": 10}, {"label": "ב", "value": 5}])
        self.assertIn("height:100%", markup)


class LayoutTest(AppTestCase):
    def setUp(self):
        super().setUp()
        seed()

    def test_member_sidebar_lists_every_area(self):
        client = self.new_client()
        client.login("noa@example.com", "Aa123456")
        page = client.get("/women/dashboard").text
        for label in ("דשבורד", "האימונים שלי", "תוכניות", "תפריט אוכל", "רשימת קניות",
                      "מעקב התקדמות", "קהילה", "AI Coach", "הגדרות"):
            self.assertIn(label, page, label)

    def test_admin_sidebar_lists_every_area(self):
        client = self.new_client()
        client.login("admin@example.com", "Aa123456")
        page = client.get("/admin").text
        # "&" arrives escaped, which is the point of rendering through esc().
        for label in ("דשבורד ניהולי", "משתמשים", "מנויים ותשלומים", "תוכן וסרטונים",
                      "תוכניות ומתכונים", "AI &amp; אוטומציה", "דוחות וסטטיסטיקות", "הגדרות מערכת"):
            self.assertIn(label, page, label)

    def test_themes_are_distinct_per_area(self):
        member = self.new_client()
        member.login("noa@example.com", "Aa123456")
        admin = self.new_client()
        admin.login("admin@example.com", "Aa123456")
        self.assertIn("theme-women", member.get("/women/dashboard").text)
        self.assertIn("theme-admin", admin.get("/admin").text)

    def test_stylesheets_and_scripts_are_first_party(self):
        page = self.client.get("/").text
        self.assertNotIn("http://", page.split("</head>")[0].replace("http://www.w3.org", ""))
        self.assertIn('href="/static/css/tokens.css"', page)
        self.assertIn('src="/static/js/app.js"', page)

    def test_responsive_breakpoints_are_defined(self):
        css = self.client.get("/static/css/layout.css").text
        for breakpoint in ("640px", "900px", "1080px"):
            self.assertIn(f"min-width: {breakpoint}", css)


class AnalyticsTest(AppTestCase):
    def test_signup_and_path_selection_are_tracked(self):
        self.client.signup("women", "a@b.co")
        names = {row["name"] for row in insights.event_counts(1)}
        self.assertIn(analytics.SIGNUP, names)
        self.assertIn(analytics.GENDER_SELECTED, names)

    def test_events_carry_the_path(self):
        self.client.signup("men", "m@b.co")
        rows = {row["name"]: row for row in insights.event_counts(1)}
        self.assertEqual(rows[analytics.GENDER_SELECTED]["male"], 1)
        self.assertEqual(rows[analytics.GENDER_SELECTED]["female"], 0)

    def test_funnel_is_ordered_and_complete(self):
        seed()
        client = self.new_client()
        client.login("noa@example.com", "Aa123456")
        video = 1
        client.post(f"/women/workouts/{video}/complete")
        steps = [step["name"] for step in insights.funnel(list(analytics.FUNNEL))]
        self.assertEqual(steps, list(analytics.FUNNEL))

    def test_tracking_never_raises(self):
        analytics.track("some_event", user_id=None, gender_path=None, weird=object())
