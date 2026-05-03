from aiogram import Router

from app.bot.handlers import admin, common, games, moderation_forum, profile, support, topic_moderation


def build_router() -> Router:
    router = Router()
    router.include_router(topic_moderation.router)
    router.include_router(admin.router)
    router.include_router(common.router)
    router.include_router(profile.router)
    router.include_router(moderation_forum.router)
    router.include_router(games.router)
    router.include_router(support.router)
    return router

