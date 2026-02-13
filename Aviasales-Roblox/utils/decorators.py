import discord
import functools
import logging
import traceback
from typing import Callable, Any

logger = logging.getLogger('aviasales_bot')

def handle_errors(error_message: str = "Произошла ошибка при выполнении команды"):
    """Декоратор для обработки ошибок в командах Discord"""
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
            try:
                return await func(self, interaction, *args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {str(e)}")
                logger.error(traceback.format_exc())
                
                error_embed = discord.Embed(
                    title="❌ Ошибка",
                    description=f"{error_message}\n```py\n{str(e)[:1000]}```",
                    color=discord.Color.red()
                )
                
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send(embed=error_embed, ephemeral=True)
                    else:
                        await interaction.response.send_message(embed=error_embed, ephemeral=True)
                except:
                    pass
        return wrapper
    return decorator
