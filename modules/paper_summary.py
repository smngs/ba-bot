import os
import sys
import datetime

import discord
from discord import app_commands
from discord.ext import commands

import json
import ujson
import aiohttp
import arxiv

from typing import List

from config.discord import DISCORD_SERVER_ID
from config.openai import OPENAI_API_KEY

SYSTEM = """
### 指示 ###
論文の内容を理解した上で，重要なポイントを箇条書きで3点書いてください。

### 箇条書きの制約 ###
- 最大3個
- 日本語
- 箇条書き1個を50文字以内

### 対象とする論文の内容 ###
{text}

### 出力形式 ###
タイトル（和名）

- 箇条書き1
- 箇条書き2
- 箇条書き3
"""

async def get_chatai_response(messages):
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + str(OPENAI_API_KEY)
    }

    data_json = {
        "model": "gpt-3.5-turbo",
        "messages": messages
    }

    async with aiohttp.ClientSession("https://api.openai.com", json_serialize=ujson.dumps) as session:
        async with session.post("/v1/chat/completions", headers=headers, json=data_json) as r:
            if r.status == 200:
                json_body = await r.json()
                return json_body["choices"][0]["message"]["content"]


async def search_arxiv(keyword: str, max_results: int=1, categories: List[str]=[], from_date: datetime.datetime="", to_date: datetime.datetime=""):
    # TODO: aiohttp で書き直す
    # QUERY_TEMPLATE = '%28 ti:%22{}%22 OR abs:%22{}%22 %29 AND submittedDate: [{} TO {}]'

    query = '%28 ti:%22{}%22 OR abs:%22{}%22 %29'.format(keyword, keyword)

    if (len(categories) != 0):
        query +=  ' AND %28 '
        for i, category in enumerate(categories):
            query += ' cat:%22{}%22 '.format(category)
            if (i == len(categories)-1):
                query += ' %29 '
            else:
                query += ' OR '

    if (from_date != "" and to_date != ""):
        query +=  'AND submittedDate: [{} TO {}]'.format(from_date.strftime("%Y%m%d%H%M%S"), to_date.strftime("%Y%m%d%H%M%S"))

    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    result_list = []
    for result in search.results():
        result_list.append(result)

    return result_list

def generate_embed(prompt: str, user: discord.User) -> discord.Embed:
    embed = discord.Embed(
        title=prompt,
        color=0x80A89C,
    )
    embed.set_author(
        name=user.display_name,
        icon_url=user.avatar.url,
    )
    return embed

def generate_paper_embed(title: str, url: str, published: str, categories: str, summary: str, user: discord.User) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        url=url,
        color=0x00FFFF,
    )
    embed.add_field(name="Published", value=published, inline=True)
    embed.add_field(name="Categories", value=categories, inline=True)
    embed.add_field(name="Summary", value=summary, inline=False)

    embed.set_author(
        name=user.display_name,
        icon_url=user.avatar.url,
    )
    return embed


class PaperSummary(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="search_paper", description="arxiv 上の論文を検索します（投稿日時順）．")
    @discord.app_commands.describe(
        keyword="検索キーワードを指定します．",
        categories="検索するカテゴリーを指定します．カンマ区切りで複数のカテゴリを指定します（OR 検索）．",
        max_result="取得する件数（10 件まで，なるべく少なく設定せよ）を指定します．",
    )
    async def search_paper(self, ctx: discord.Interaction, keyword: str, max_result: int=1, categories: str=""):
        await ctx.response.defer()

        if (max_result > 10):
            ctx.followup.send("取得件数が多すぎます．10 件以下に設定して再度実行してください．")
            return

        async with ctx.channel.typing():
            # to_date = datetime.datetime.today() - datetime.timedelta(days=7)
            # from_date = to_date - datetime.timedelta(days=14)

            if categories != "":
                category_list = [x.strip() for x in categories.split(',')]
            else:
                category_list = []

            result_list = await search_arxiv(keyword, max_result, category_list)

            if len(result_list) == 0:
                ctx.followup.send("検索結果が見つかりませんでした．")

            for result in result_list:
                # ChatGPT で要約
                prompt = f"title: {result.title}\nbody: {result.summary}"
                jp_summarize = await get_chatai_response(
                    [
                        {
                            "role": "system",
                            "content": SYSTEM
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                )

                embed = generate_paper_embed(result.title, result, result.published, result.categories, jp_summarize, ctx.user)
                await ctx.followup.send(embed=embed)

async def setup(bot: commands.Bot) -> None:
    if DISCORD_SERVER_ID:
        guild = discord.Object(id=int(DISCORD_SERVER_ID))
        await bot.add_cog(PaperSummary(bot), guild=guild)
    else:
        await bot.add_cog(PaperSummary(bot))
