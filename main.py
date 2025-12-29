import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import asyncpg
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from webserver import keep_alive

keep_alive()

# Load environment variables from .env file
load_dotenv()


# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Database connection pool (will be initialized in on_ready)
db_pool = None

# Initialize VADER sentiment analyzer
sentiment_analyzer = SentimentIntensityAnalyzer()


def analyze_sentiment(text: str) -> str:
    """
    Analyze the sentiment of a text string.
    
    Args:
        text: The text to analyze
        
    Returns:
        "Positive", "Negative", or "Neutral" based on VADER compound score
    """
    try:
        scores = sentiment_analyzer.polarity_scores(text)
        compound = scores['compound']
        
        # Thresholds for sentiment classification
        if compound >= 0.05:
            return "Positive"
        elif compound <= -0.05:
            return "Negative"
        else:
            return "Neutral"
    except Exception as e:
        print(f"Error analyzing sentiment: {e}")
        return "Neutral"  # Default to neutral on error


@bot.event
async def on_ready():
    global db_pool
    print(f'{bot.user} has logged in!')
    print(f'Bot is in {len(bot.guilds)} server(s)')
    
    # Initialize database connection pool
    try:
        # Option 1: Use DATABASE_URL if you have a full connection string
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            db_pool = await asyncpg.create_pool(database_url, min_size=1, max_size=10)
            print("✅ Connected to database using DATABASE_URL")
        else:
            # Option 2: Use individual connection parameters
            db_pool = await asyncpg.create_pool(
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                host=os.getenv("DB_HOST"),
                port=int(os.getenv("DB_PORT", 5432)),
                database=os.getenv("DB_NAME"),
                min_size=1,
                max_size=10
            )
            print("✅ Connected to database using individual parameters")
        
        # Create tables if they don't exist
        await create_tables()
        
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        print("Bot will continue running but database features will not work.")
    
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'Failed to sync commands: {e}')


async def create_tables():
    """Create database tables if they don't exist"""
    if not db_pool:
        return
    
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS reviews (
                    id SERIAL PRIMARY KEY,
                    player TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            print("✅ Database tables created/verified")
    except Exception as e:
        print(f"❌ Error creating tables: {e}")


@bot.event
async def on_error(event, *args, **kwargs):
    print(f'An error occurred in {event}')
    import traceback
    traceback.print_exc()


@bot.tree.command(name="review", description="Submit a review for a Discord user")
@app_commands.describe(
    user="The Discord user to review",
    review_text="The review text"
)
async def review(interaction: discord.Interaction, user: discord.User, review_text: str):
    """
    Slash command to review a Discord user.
    
    Usage: /review @username "review text here"
    """
    try:
        # Create an embed for the review
        embed = discord.Embed(
            title="📝 New Review",
            description=f"**Reviewed User:** {user.mention}\n**Reviewer:** {interaction.user.mention}\n\n**Review:**\n{review_text}",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"Review submitted by {interaction.user.display_name}")
        embed.timestamp = discord.utils.utcnow()
        
        await interaction.response.send_message(embed=embed)
        
        # Save review to database
        if db_pool:
            try:
                async with db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO reviews (player, reviewer, text)
                        VALUES ($1, $2, $3)
                    """, user.name, interaction.user.name, review_text)
                    print(f"✅ Saved review to database: {user.name} reviewed by {interaction.user.name}")
            except Exception as e:
                print(f"❌ Error saving review to database: {e}")
        else:
            print("⚠️ Database not connected, review not saved")
            
    except Exception as e:
        print(f"Error in review command: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred while processing your review. Please try again.", ephemeral=True)
        else:
            await interaction.followup.send("❌ An error occurred while processing your review. Please try again.", ephemeral=True)


@bot.tree.command(name="get_reviews", description="Get all reviews for a player")
@app_commands.describe(
    user="The Discord user to get reviews for"
)
async def get_reviews(interaction: discord.Interaction, user: discord.User):
    """
    Slash command to retrieve all reviews for a player.
    
    Usage: /get_reviews user:@username
    """
    try:
        # Use the provided Discord user
        target_user = user
        player_username = target_user.name
        
        if not db_pool:
            await interaction.response.send_message("❌ Database is not connected. Please contact the bot administrator.", ephemeral=True)
            return
        
        # Fetch reviews from database
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, player, reviewer, text, created_at
                    FROM reviews
                    WHERE player = $1
                    ORDER BY created_at DESC
                """, player_username)
        except Exception as e:
            print(f"❌ Error fetching reviews for {player_username}: {e}")
            await interaction.response.send_message("❌ An error occurred while fetching reviews. Please try again.", ephemeral=True)
            return
        
        if not rows:
            await interaction.response.send_message(f"📭 No reviews found for {target_user.mention}.", ephemeral=True)
            return
        
        # Analyze sentiment for all reviews
        sentiment_counts = {"Positive": 0, "Negative": 0, "Neutral": 0}
        for review in rows:
            try:
                sentiment = analyze_sentiment(review['text'])
                sentiment_counts[sentiment] += 1
            except Exception as e:
                print(f"Error analyzing sentiment for review {review['id']}: {e}")
                sentiment_counts["Neutral"] += 1  # Default to neutral on error
        
        # Calculate percentages
        total_reviews = len(rows)
        positive_pct = round((sentiment_counts["Positive"] / total_reviews) * 100) if total_reviews > 0 else 0
        negative_pct = round((sentiment_counts["Negative"] / total_reviews) * 100) if total_reviews > 0 else 0
        neutral_pct = round((sentiment_counts["Neutral"] / total_reviews) * 100) if total_reviews > 0 else 0
        
        # Format sentiment summary
        sentiment_summary = f"Overall Sentiment: {positive_pct}% Positive, {negative_pct}% Negative, {neutral_pct}% Neutral"
        
        # Create embed with reviews
        embed = discord.Embed(
            title=f"📋 Reviews for {target_user.display_name}",
            description=f"Found **{len(rows)}** review(s) for {target_user.mention}\n\n**{sentiment_summary}**",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        
        # Discord embeds have a limit of 25 fields and 6000 characters total
        # Show up to 10 most recent reviews
        reviews_to_show = rows[:10]
        
        for i, review in enumerate(reviews_to_show, 1):
            review_text = review['text']
            # Truncate if too long (Discord field value limit is 1024 chars)
            if len(review_text) > 500:
                review_text = review_text[:500] + "..."
            
            # Format timestamp
            created_at = review['created_at']
            if isinstance(created_at, str):
                timestamp_str = created_at
            else:
                timestamp_str = created_at.strftime("%Y-%m-%d %H:%M:%S")
            
            embed.add_field(
                name=f"Review #{i} by {review['reviewer']}",
                value=f"{review_text}\n*{timestamp_str}*",
                inline=False
            )
        
        if len(rows) > 10:
            embed.set_footer(text=f"Showing 10 of {len(rows)} reviews. Most recent first.")
        else:
            embed.set_footer(text="Most recent first.")
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        print(f"Error in reviews command: {e}")
        import traceback
        traceback.print_exc()
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred while fetching reviews. Please try again.", ephemeral=True)
        else:
            await interaction.followup.send("❌ An error occurred while fetching reviews. Please try again.", ephemeral=True)


# Run the bot
if __name__ == "__main__":
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        print("Error: DISCORD_BOT_TOKEN environment variable not set!")
        print("Please set your Discord bot token as an environment variable.")
        exit(1)
    else:
        try:
            bot.run(token, reconnect=True)
        except KeyboardInterrupt:
            print("\nBot is shutting down...")
        except Exception as e:
            print(f"Bot crashed with error: {e}")
            raise
