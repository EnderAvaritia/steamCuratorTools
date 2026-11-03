from __future__ import annotations

from steamCuratorTools.emailHelper.settings import isValidEmail
from steamCuratorTools.emailHelper.templates import (
    defaultTemplates,
    renderTemplate,
    templateKinds,
)


def testRenderTemplateSubstitutesKnownPlaceholders() -> None:
    text = renderTemplate(
        "给 {publisher_name} 的《{game_name}》({appid})\n{steam_url}",
        {
            "publisher_name": "Studio",
            "game_name": "Game",
            "appid": "123",
            "steam_url": "https://example.com/app/123",
        },
    )
    assert "Studio" in text
    assert "Game" in text
    assert "123" in text
    assert "https://example.com/app/123" in text


def testRenderTemplateLeavesUnknownAndLiteralBracesUntouched() -> None:
    text = renderTemplate('{"json": true} {unknown} {game_name}', {"game_name": "G"})
    assert text == '{"json": true} {unknown} G'


def testBuiltInTemplatesAreComplete() -> None:
    assert tuple(defaultTemplates) == templateKinds
    for content in defaultTemplates.values():
        assert content.strip()


def testEmailValidation() -> None:
    assert isValidEmail("press@example.com")
    assert isValidEmail("a.b+c@sub.example.org")
    assert not isValidEmail("not-an-email")
    assert not isValidEmail("a@b")
    assert not isValidEmail("")