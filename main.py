import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import asyncpg
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import asyncio
import time
from datetime import datetime

# Load environment variables from .env file
load_dotenv()


# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Database connection pool (will be initialized in on_ready)
db_pool = None

# Track if commands have been synced (to prevent rate limiting)
commands_synced = False

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
    global db_pool, commands_synced
    print(f'{bot.user} has logged in!')
    print(f'Bot is in {len(bot.guilds)} server(s)')
    
    # Initialize database connection pool (only if not already connected)
    if not db_pool:
        try:
            # Option 1: Use DATABASE_URL if you have a full connection string
            database_url = os.getenv('DATABASE_URL')
            if database_url:
                # Disable prepared statements for pgbouncer compatibility (Supabase uses pgbouncer)
                db_pool = await asyncpg.create_pool(
                    database_url, 
                    min_size=1, 
                    max_size=10,
                    statement_cache_size=0  # Disable prepared statements for pgbouncer
                )
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
                    max_size=10,
                    statement_cache_size=0  # Disable prepared statements for pgbouncer
                )
                print("✅ Connected to database using individual parameters")
            
            # Create tables if they don't exist
            await create_tables()
            
        except Exception as e:
            print(f"❌ Failed to connect to database: {e}")
            print("Bot will continue running but database features will not work.")
    
    # Only sync commands once to avoid rate limiting (429 errors)
    if not commands_synced:
        try:
            synced = await bot.tree.sync()
            print(f'✅ Synced {len(synced)} command(s)')
            commands_synced = True
        except discord.HTTPException as e:
            if e.status == 429:
                print(f'⚠️ Rate limited while syncing commands. Commands may already be synced.')
                print(f'   Discord allows command syncing once per hour. Bot will continue running.')
            else:
                print(f'❌ Failed to sync commands: {e}')
        except Exception as e:
            print(f'❌ Failed to sync commands: {e}')
    else:
        print('ℹ️ Commands already synced, skipping to avoid rate limits')


async def create_tables():
    """Create database tables if they don't exist"""
    if not db_pool:
        return
    
    try:
        async with db_pool.acquire() as conn:
            # Create reviews table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS reviews (
                    id SERIAL PRIMARY KEY,
                    player TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create vouches table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS vouches (
                    id SERIAL PRIMARY KEY,
                    player TEXT NOT NULL,
                    host TEXT NOT NULL,
                    vouch_amount NUMERIC NOT NULL,
                    vouch_type TEXT NOT NULL CHECK (vouch_type IN ('hard', 'soft')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    edited_on TIMESTAMP,
                    UNIQUE(player, host)
                )
            """)
            
            # Add unique constraint if it doesn't exist (for existing databases)
            await conn.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint 
                        WHERE conname = 'vouches_player_host_key'
                    ) THEN
                        ALTER TABLE vouches ADD CONSTRAINT vouches_player_host_key UNIQUE (player, host);
                    END IF;
                END $$;
            """)
            
            # Create indexes for vouches
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_vouches_player 
                ON vouches(player)
            """)
            
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_vouches_type_amount 
                ON vouches(vouch_type, vouch_amount DESC)
            """)
            
            # Create debts table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS debts (
                    id SERIAL PRIMARY KEY,
                    player TEXT NOT NULL,
                    host TEXT NOT NULL,
                    debt_amount NUMERIC NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    edited_on TIMESTAMP,
                    UNIQUE(player, host)
                )
            """)
            
            # Add unique constraint if it doesn't exist (for existing databases)
            await conn.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint 
                        WHERE conname = 'debts_player_host_key'
                    ) THEN
                        ALTER TABLE debts ADD CONSTRAINT debts_player_host_key UNIQUE (player, host);
                    END IF;
                END $$;
            """)
            
            # Add edited_on column if it doesn't exist (for existing databases)
            await conn.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='debts' AND column_name='edited_on'
                    ) THEN
                        ALTER TABLE debts ADD COLUMN edited_on TIMESTAMP;
                    END IF;
                END $$;
            """)
            
            # Create indexes for debts
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_debts_player 
                ON debts(player)
            """)
            
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_debts_amount 
                ON debts(debt_amount DESC)
            """)
            
            print("✅ Database tables created/verified")
    except Exception as e:
        print(f"❌ Error creating tables: {e}")


@bot.event
async def on_error(event, *args, **kwargs):
    print(f'An error occurred in {event}')
    import traceback
    traceback.print_exc()


@bot.tree.command(name="add_review", description="Submit a review for a Discord user")
@app_commands.describe(
    user="The Discord user to review",
    review_text="The review text"
)
async def review(interaction: discord.Interaction, user: discord.User, review_text: str):
    """
    Slash command to review a Discord user.
    
    Usage: /add_review @username "review text here"
    """
    try:
        # Try to get a safe mention - use display_name if user not in guild
        try:
            # Check if user is in the guild
            if interaction.guild and interaction.guild.get_member(user.id):
                user_display = user.mention
            else:
                user_display = f"{user.display_name} ({user.name})"
        except:
            user_display = f"{user.display_name} ({user.name})"
        
        # Create an embed for the review
        embed = discord.Embed(
            title="📝 New Review",
            description=f"**Reviewed User:** {user_display}\n**Reviewer:** {interaction.user.mention}\n\n**Review:**\n{review_text}",
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


@bot.tree.command(name="get_review", description="Get all reviews for a player")
@app_commands.describe(
    user="The Discord user to get reviews for"
)
async def get_reviews(interaction: discord.Interaction, user: discord.User):
    """
    Slash command to retrieve all reviews for a player.
    
    Usage: /get_review user:@username
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


@bot.tree.command(name="add_vouch", description="Vouch for a player with an amount (hard or soft)")
@app_commands.describe(
    player="The Discord user to vouch for",
    amount="The amount to vouch for (e.g., 100)",
    vouch_type="Type of vouch: hard or soft"
)
@app_commands.choices(vouch_type=[
    app_commands.Choice(name="hard", value="hard"),
    app_commands.Choice(name="soft", value="soft")
])
async def vouch(interaction: discord.Interaction, player: discord.User, amount: int, vouch_type: app_commands.Choice[str]):
    """
    Slash command to vouch for a player.
    
    Usage: /add_vouch user:@username amount:100 vouch_type:hard
    """
    try:
        if not db_pool:
            await interaction.response.send_message("❌ Database is not connected. Please contact the bot administrator.", ephemeral=True)
            return
        
        # Get the vouch type value from the choice
        vouch_type_value = vouch_type.value
        
        # Validate amount
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
            return
        
        # Save or update vouch to database (UPSERT)
        is_update = False
        try:
            async with db_pool.acquire() as conn:
                # Check if vouch already exists
                existing = await conn.fetchrow("""
                    SELECT id, vouch_amount, vouch_type, created_at, edited_on
                    FROM vouches
                    WHERE player = $1 AND host = $2
                """, player.name, interaction.user.name)
                
                if existing:
                    # Update existing vouch
                    await conn.execute("""
                        UPDATE vouches
                        SET vouch_amount = $1, vouch_type = $2, edited_on = CURRENT_TIMESTAMP
                        WHERE player = $3 AND host = $4
                    """, amount, vouch_type_value, player.name, interaction.user.name)
                    is_update = True
                    print(f"✅ Updated vouch in database: {player.name} vouched by {interaction.user.name} for ${amount} ({vouch_type_value})")
                else:
                    # Insert new vouch
                    await conn.execute("""
                        INSERT INTO vouches (player, host, vouch_amount, vouch_type)
                        VALUES ($1, $2, $3, $4)
                    """, player.name, interaction.user.name, amount, vouch_type_value)
                    is_update = False
                    print(f"✅ Saved vouch to database: {player.name} vouched by {interaction.user.name} for ${amount} ({vouch_type_value})")
        except Exception as e:
            print(f"❌ Error saving vouch to database: {e}")
            await interaction.response.send_message("❌ An error occurred while saving the vouch. Please try again.", ephemeral=True)
            return
        
        # Create embed for the vouch
        title = "💵 Vouch Updated" if is_update else "💵 New Vouch"
        
        # Try to get a safe mention - use display_name if user not in guild
        try:
            # Check if player is in the guild
            if interaction.guild and interaction.guild.get_member(player.id):
                player_display = player.mention
            else:
                player_display = f"{player.display_name} ({player.name})"
        except:
            player_display = f"{player.display_name} ({player.name})"
        
        embed = discord.Embed(
            title=title,
            description=f"**Player:** {player_display}\n**Host:** {interaction.user.mention}\n**Amount:** ${amount:,.0f}\n**Type:** {vouch_type_value.upper()}",
            color=discord.Color.green() if vouch_type_value == "hard" else discord.Color.orange()
        )
        embed.set_thumbnail(url=player.display_avatar.url)
        embed.set_footer(text=f"Vouch {'updated' if is_update else 'submitted'} by {interaction.user.display_name}")
        embed.timestamp = discord.utils.utcnow()
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        print(f"Error in vouch command: {e}")
        import traceback
        traceback.print_exc()
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred while processing your vouch. Please try again.", ephemeral=True)
        else:
            await interaction.followup.send("❌ An error occurred while processing your vouch. Please try again.", ephemeral=True)


@bot.tree.command(name="get_vouch", description="Get all vouches for a player")
@app_commands.describe(
    player="The Discord user to get vouches for"
)
async def get_vouch(interaction: discord.Interaction, player: discord.User):
    """
    Slash command to retrieve all vouches for a player.
    
    Usage: /get_vouch user:@username
    """
    try:
        target_user = player
        player_username = target_user.name
        
        if not db_pool:
            await interaction.response.send_message("❌ Database is not connected. Please contact the bot administrator.", ephemeral=True)
            return
        
        # Fetch vouches from database, ordered by vouch_type ASC, vouch_amount DESC
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, player, host, vouch_amount, vouch_type, created_at, edited_on
                    FROM vouches
                    WHERE player = $1
                    ORDER BY vouch_type ASC, vouch_amount DESC
                """, player_username)
        except Exception as e:
            print(f"❌ Error fetching vouches for {player_username}: {e}")
            await interaction.response.send_message("❌ An error occurred while fetching vouches. Please try again.", ephemeral=True)
            return
        
        if not rows:
            await interaction.response.send_message(f"📭 No vouches found for {target_user.mention}.", ephemeral=True)
            return
        
        # Create embed with vouches
        embed = discord.Embed(
            title=f"💵 Vouches for {target_user.display_name}",
            description=f"Found **{len(rows)}** vouch(es) for {target_user.mention}",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        
        # Group vouches by type
        hard_vouches = [row for row in rows if row['vouch_type'] == 'hard']
        soft_vouches = [row for row in rows if row['vouch_type'] == 'soft']
        
        # Add hard vouches first
        if hard_vouches:
            hard_text = ""
            for vouch in hard_vouches:
                # Use edited_on if available, otherwise use created_at
                date_to_format = vouch.get('edited_on') or vouch['created_at']
                
                # Format date to mm/dd/yyyy
                if isinstance(date_to_format, str):
                    # If it's a string, try to parse it
                    try:
                        date_obj = datetime.fromisoformat(date_to_format.replace('Z', '+00:00'))
                        formatted_date = date_obj.strftime('%m/%d/%Y')
                    except:
                        formatted_date = date_to_format[:10] if len(date_to_format) >= 10 else date_to_format
                elif date_to_format:
                    formatted_date = date_to_format.strftime('%m/%d/%Y')
                else:
                    # Fallback to created_at if edited_on is None
                    created_at = vouch['created_at']
                    if isinstance(created_at, str):
                        try:
                            date_obj = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            formatted_date = date_obj.strftime('%m/%d/%Y')
                        except:
                            formatted_date = created_at[:10] if len(created_at) >= 10 else created_at
                    else:
                        formatted_date = created_at.strftime('%m/%d/%Y')
                
                hard_text += f"{vouch['host']}: ${int(vouch['vouch_amount'])} on {formatted_date}\n"
            if len(hard_text) > 1024:
                hard_text = hard_text[:1020] + "..."
            embed.add_field(
                name=f"🟢 Hard Vouches ({len(hard_vouches)})",
                value=hard_text or "None",
                inline=False
            )
        
        # Add soft vouches
        if soft_vouches:
            soft_text = ""
            for vouch in soft_vouches:
                # Use edited_on if available, otherwise use created_at
                date_to_format = vouch.get('edited_on') or vouch['created_at']
                
                # Format date to mm/dd/yyyy
                if isinstance(date_to_format, str):
                    # If it's a string, try to parse it
                    try:
                        date_obj = datetime.fromisoformat(date_to_format.replace('Z', '+00:00'))
                        formatted_date = date_obj.strftime('%m/%d/%Y')
                    except:
                        formatted_date = date_to_format[:10] if len(date_to_format) >= 10 else date_to_format
                elif date_to_format:
                    formatted_date = date_to_format.strftime('%m/%d/%Y')
                else:
                    # Fallback to created_at if edited_on is None
                    created_at = vouch['created_at']
                    if isinstance(created_at, str):
                        try:
                            date_obj = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            formatted_date = date_obj.strftime('%m/%d/%Y')
                        except:
                            formatted_date = created_at[:10] if len(created_at) >= 10 else created_at
                    else:
                        formatted_date = created_at.strftime('%m/%d/%Y')
                
                soft_text += f"{vouch['host']}: ${int(vouch['vouch_amount'])} on {formatted_date}\n"
            if len(soft_text) > 1024:
                soft_text = soft_text[:1020] + "..."
            embed.add_field(
                name=f"🟡 Soft Vouches ({len(soft_vouches)})",
                value=soft_text or "None",
                inline=False
            )
        
        embed.set_footer(text="Ordered by type (hard first), then by vouch amount (highest first)")
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        print(f"Error in get_vouch command: {e}")
        import traceback
        traceback.print_exc()
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred while fetching vouches. Please try again.", ephemeral=True)
        else:
            await interaction.followup.send("❌ An error occurred while fetching vouches. Please try again.", ephemeral=True)


@bot.tree.command(name="remove_vouch", description="Remove your vouch for a player")
@app_commands.describe(
    player="The Discord user to remove your vouch for"
)
async def remove_vouch(interaction: discord.Interaction, player: discord.User):
    """
    Slash command to remove your vouch for a player.
    
    Usage: /remove_vouch user:@username
    """
    try:
        target_user = player
        player_username = target_user.name
        host_username = interaction.user.name
        
        if not db_pool:
            await interaction.response.send_message("❌ Database is not connected. Please contact the bot administrator.", ephemeral=True)
            return
        
        # Check if vouch exists and delete it
        try:
            async with db_pool.acquire() as conn:
                # Check if vouch exists
                existing = await conn.fetchrow("""
                    SELECT id, vouch_amount, vouch_type
                    FROM vouches
                    WHERE player = $1 AND host = $2
                """, player_username, host_username)
                
                if existing:
                    # Delete the vouch
                    await conn.execute("""
                        DELETE FROM vouches
                        WHERE player = $1 AND host = $2
                    """, player_username, host_username)
                    
                    print(f"✅ Removed vouch from database: {player_username} vouch by {host_username}")
                    
                    # Create success embed
                    embed = discord.Embed(
                        title="🗑️ Vouch Removed",
                        description=f"Your vouch for {target_user.mention} has been removed.",
                        color=discord.Color.red()
                    )
                    embed.set_thumbnail(url=target_user.display_avatar.url)
                    embed.set_footer(text=f"Vouch removed by {interaction.user.display_name}")
                    embed.timestamp = discord.utils.utcnow()
                    
                    await interaction.response.send_message(embed=embed)
                else:
                    # No vouch found
                    await interaction.response.send_message(
                        f"📭 You don't have a vouch for {target_user.mention} to remove.",
                        ephemeral=True
                    )
        except Exception as e:
            print(f"❌ Error removing vouch from database: {e}")
            await interaction.response.send_message("❌ An error occurred while removing the vouch. Please try again.", ephemeral=True)
            return
        
    except Exception as e:
        print(f"Error in remove_vouch command: {e}")
        import traceback
        traceback.print_exc()
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred while removing the vouch. Please try again.", ephemeral=True)
        else:
            await interaction.followup.send("❌ An error occurred while removing the vouch. Please try again.", ephemeral=True)


@bot.tree.command(name="add_debt", description="Add or update a debt for a player")
@app_commands.describe(
    player="The Discord user to add a debt for",
    amount="The debt amount (e.g., 100)"
)
async def debt(interaction: discord.Interaction, player: discord.User, amount: float):
    """
    Slash command to add or update a debt for a player.
    
    Usage: /add_debt user:@username amount:100
    """
    try:
        if not db_pool:
            await interaction.response.send_message("❌ Database is not connected. Please contact the bot administrator.", ephemeral=True)
            return
        
        # Validate amount
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
            return
        
        # Add debt to database (add to existing or create new)
        previous_amount = None
        new_amount = amount
        try:
            async with db_pool.acquire() as conn:
                # Check if debt already exists
                existing = await conn.fetchrow("""
                    SELECT id, debt_amount, created_at, edited_on
                    FROM debts
                    WHERE player = $1 AND host = $2
                """, player.name, interaction.user.name)
                
                if existing:
                    # Add to existing debt
                    previous_amount = float(existing['debt_amount'])
                    new_amount = previous_amount + amount
                    await conn.execute("""
                        UPDATE debts
                        SET debt_amount = $1, edited_on = CURRENT_TIMESTAMP
                        WHERE player = $2 AND host = $3
                    """, new_amount, player.name, interaction.user.name)
                    print(f"✅ Added to debt in database: {player.name} debt by {interaction.user.name} - added ${amount} (total: ${new_amount})")
                else:
                    # Insert new debt
                    await conn.execute("""
                        INSERT INTO debts (player, host, debt_amount)
                        VALUES ($1, $2, $3)
                    """, player.name, interaction.user.name, amount)
                    print(f"✅ Saved debt to database: {player.name} debt by {interaction.user.name} for ${amount}")
        except Exception as e:
            print(f"❌ Error saving debt to database: {e}")
            await interaction.response.send_message("❌ An error occurred while saving the debt. Please try again.", ephemeral=True)
            return
        
        # Create embed for the debt
        # Try to get a safe mention - use display_name if user not in guild
        try:
            # Check if player is in the guild
            if interaction.guild and interaction.guild.get_member(player.id):
                player_display = player.mention
            else:
                player_display = f"{player.display_name} ({player.name})"
        except:
            player_display = f"{player.display_name} ({player.name})"
        
        if previous_amount is not None:
            # Debt was added to existing
            title = "💸 Debt Added"
            description = f"**Player:** {player_display}\n**Host:** {interaction.user.mention}\n**Added:** ${amount:,.0f}\n**Previous Total:** ${previous_amount:,.0f}\n**New Total:** ${new_amount:,.0f}"
        else:
            # New debt created
            title = "💸 New Debt"
            description = f"**Player:** {player_display}\n**Host:** {interaction.user.mention}\n**Debt Amount:** ${amount:,.0f}"
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.red()
        )
        embed.set_thumbnail(url=player.display_avatar.url)
        embed.set_footer(text=f"Debt {'added' if previous_amount is not None else 'submitted'} by {interaction.user.display_name}")
        embed.timestamp = discord.utils.utcnow()
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        print(f"Error in debt command: {e}")
        import traceback
        traceback.print_exc()
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred while processing your debt. Please try again.", ephemeral=True)
        else:
            await interaction.followup.send("❌ An error occurred while processing your debt. Please try again.", ephemeral=True)


@bot.tree.command(name="remove_debt", description="Clear or reduce a debt for a player")
@app_commands.describe(
    player="The Discord user to clear debt for",
    amount="The amount to clear (leave empty to clear all)"
)
async def remove_debt(interaction: discord.Interaction, player: discord.User, amount: float = None):
    """
    Slash command to clear or reduce a debt for a player.
    
    Usage: /remove_debt user:@username amount:50
    or: /remove_debt user:@username (to clear all)
    """
    try:
        target_user = player
        player_username = target_user.name
        host_username = interaction.user.name
        
        if not db_pool:
            await interaction.response.send_message("❌ Database is not connected. Please contact the bot administrator.", ephemeral=True)
            return
        
        try:
            async with db_pool.acquire() as conn:
                # Check if debt exists
                existing = await conn.fetchrow("""
                    SELECT id, debt_amount
                    FROM debts
                    WHERE player = $1 AND host = $2
                """, player_username, host_username)
                
                if not existing:
                    await interaction.response.send_message(
                        f"📭 You don't have a debt recorded for {target_user.mention}.",
                        ephemeral=True
                    )
                    return
                
                current_debt = float(existing['debt_amount'])
                
                if amount is None:
                    # Clear all debt
                    await conn.execute("""
                        DELETE FROM debts
                        WHERE player = $1 AND host = $2
                    """, player_username, host_username)
                    
                    print(f"✅ Cleared debt from database: {player_username} debt by {host_username}")
                    
                    embed = discord.Embed(
                        title="✅ Debt Cleared",
                        description=f"All debt for {target_user.mention} has been cleared.\n**Previous amount:** ${current_debt:,.0f}",
                        color=discord.Color.green()
                    )
                    embed.set_thumbnail(url=target_user.display_avatar.url)
                    embed.set_footer(text=f"Debt cleared by {interaction.user.display_name}")
                    embed.timestamp = discord.utils.utcnow()
                    
                    await interaction.response.send_message(embed=embed)
                else:
                    # Reduce debt by amount
                    if amount <= 0:
                        await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
                        return
                    
                    new_debt = current_debt - amount
                    
                    if new_debt <= 0:
                        # Clear the debt completely
                        await conn.execute("""
                            DELETE FROM debts
                            WHERE player = $1 AND host = $2
                        """, player_username, host_username)
                        
                        print(f"✅ Cleared debt from database: {player_username} debt by {host_username}")
                        
                        embed = discord.Embed(
                            title="✅ Debt Cleared",
                            description=f"Debt for {target_user.mention} has been fully cleared.\n**Previous amount:** ${current_debt:,.0f}\n**Cleared:** ${amount:,.0f}",
                            color=discord.Color.green()
                        )
                    else:
                        # Update debt amount
                        await conn.execute("""
                            UPDATE debts
                            SET debt_amount = $1, edited_on = CURRENT_TIMESTAMP
                            WHERE player = $2 AND host = $3
                        """, new_debt, player_username, host_username)
                        
                        print(f"✅ Reduced debt in database: {player_username} debt by {host_username} from ${current_debt} to ${new_debt}")
                        
                        embed = discord.Embed(
                            title="💸 Debt Reduced",
                            description=f"Debt for {target_user.mention} has been reduced.\n**Previous amount:** ${current_debt:,.0f}\n**Reduced by:** ${amount:,.0f}\n**New amount:** ${new_debt:,.0f}",
                            color=discord.Color.orange()
                        )
                    
                    embed.set_thumbnail(url=target_user.display_avatar.url)
                    embed.set_footer(text=f"Debt updated by {interaction.user.display_name}")
                    embed.timestamp = discord.utils.utcnow()
                    
                    await interaction.response.send_message(embed=embed)
        except Exception as e:
            print(f"❌ Error clearing debt from database: {e}")
            await interaction.response.send_message("❌ An error occurred while clearing the debt. Please try again.", ephemeral=True)
            return
        
    except Exception as e:
        print(f"Error in remove_debt command: {e}")
        import traceback
        traceback.print_exc()
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred while clearing the debt. Please try again.", ephemeral=True)
        else:
            await interaction.followup.send("❌ An error occurred while clearing the debt. Please try again.", ephemeral=True)


@bot.tree.command(name="get_debt", description="Get all debts for a player")
@app_commands.describe(
    player="The Discord user to get debts for"
)
async def get_debt(interaction: discord.Interaction, player: discord.User):
    """
    Slash command to retrieve all debts for a player.
    
    Usage: /get_debt user:@username
    """
    try:
        target_user = player
        player_username = target_user.name
        
        if not db_pool:
            await interaction.response.send_message("❌ Database is not connected. Please contact the bot administrator.", ephemeral=True)
            return
        
        # Fetch debts from database, ordered by debt_amount DESC
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, player, host, debt_amount, created_at, edited_on
                    FROM debts
                    WHERE player = $1
                    ORDER BY debt_amount DESC
                """, player_username)
        except Exception as e:
            print(f"❌ Error fetching debts for {player_username}: {e}")
            await interaction.response.send_message("❌ An error occurred while fetching debts. Please try again.", ephemeral=True)
            return
        
        if not rows:
            await interaction.response.send_message(f"📭 No debts found for {target_user.mention}.", ephemeral=True)
            return
        
        # Get all unique hosts and try to mention them
        unique_hosts = {}
        for row in rows:
            host_username = row['host']
            if host_username not in unique_hosts:
                unique_hosts[host_username] = {'username': host_username}
        
        host_mentions = []
        # Try to mention hosts by username
        for host_data in unique_hosts.values():
            host_username = host_data['username']
            if interaction.guild:
                host_member = interaction.guild.get_member_named(host_username)
                if host_member:
                    host_mentions.append(host_member.mention)
                else:
                    host_mentions.append(f"`{host_username}`")
            else:
                host_mentions.append(f"`{host_username}`")
        
        # Create embed with debts
        hosts_text = ", ".join(host_mentions) if host_mentions else "Unknown hosts"
        embed = discord.Embed(
            title=f"💸 Debts for {target_user.display_name}",
            description=f"Found **{len(rows)}** debt(s) for {target_user.mention}\n\n**Hosts:** {hosts_text}",
            color=discord.Color.red()
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)
        
        # Add debts list
        debts_text = ""
        for debt in rows:
            # Use edited_on if available, otherwise use created_at
            date_to_format = debt.get('edited_on') or debt['created_at']
            
            # Format date to mm/dd/yyyy
            if isinstance(date_to_format, str):
                try:
                    date_obj = datetime.fromisoformat(date_to_format.replace('Z', '+00:00'))
                    formatted_date = date_obj.strftime('%m/%d/%Y')
                except:
                    formatted_date = date_to_format[:10] if len(date_to_format) >= 10 else date_to_format
            elif date_to_format:
                formatted_date = date_to_format.strftime('%m/%d/%Y')
            else:
                # Fallback to created_at if edited_on is None
                created_at = debt['created_at']
                if isinstance(created_at, str):
                    try:
                        date_obj = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        formatted_date = date_obj.strftime('%m/%d/%Y')
                    except:
                        formatted_date = created_at[:10] if len(created_at) >= 10 else created_at
                else:
                    formatted_date = created_at.strftime('%m/%d/%Y')
            
            debts_text += f"{debt['host']}: ${float(debt['debt_amount']):,.0f} on {formatted_date}\n"
        
        if len(debts_text) > 1024:
            debts_text = debts_text[:1020] + "..."
        
        embed.add_field(
            name=f"💸 Debts ({len(rows)})",
            value=debts_text or "None",
            inline=False
        )
        
        embed.set_footer(text="Ordered by debt amount (highest first)")
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        print(f"Error in get_debt command: {e}")
        import traceback
        traceback.print_exc()
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred while fetching debts. Please try again.", ephemeral=True)
        else:
            await interaction.followup.send("❌ An error occurred while fetching debts. Please try again.", ephemeral=True)


@bot.tree.command(name="get_all_debt", description="Get debt totals for all players (highest to lowest)")
async def get_all_debt(interaction: discord.Interaction):
    """
    Slash command to retrieve debts for all players, sorted by highest total debt.
    
    Usage: /get_all_debt
    """
    try:
        if not db_pool:
            await interaction.response.send_message("❌ Database is not connected. Please contact the bot administrator.", ephemeral=True)
            return

        # Fetch aggregated debts by player, highest total first
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT player, SUM(debt_amount) AS total_debt, COUNT(*) AS entry_count
                    FROM debts
                    GROUP BY player
                    ORDER BY total_debt DESC
                """)
        except Exception as e:
            print(f"❌ Error fetching all debts: {e}")
            await interaction.response.send_message("❌ An error occurred while fetching debts. Please try again.", ephemeral=True)
            return

        if not rows:
            await interaction.response.send_message("📭 No debts found.", ephemeral=True)
            return

        embed = discord.Embed(
            title="💸 All Debts",
            description=f"Found **{len(rows)}** player(s) with debt (highest first)",
            color=discord.Color.red()
        )

        # Limit to 25 fields (Discord embed limit)
        rows_to_show = rows[:25]
        for idx, row in enumerate(rows_to_show, 1):
            player_name = row["player"]
            total_debt = float(row["total_debt"])
            entry_count = row["entry_count"]
            embed.add_field(
                name=f"{idx}. {player_name}",
                value=f"${total_debt:,.0f} (entries: {entry_count})",
                inline=False
            )

        if len(rows) > 25:
            embed.set_footer(text=f"Showing top 25 of {len(rows)} players by debt (highest first)")
        else:
            embed.set_footer(text="Ordered by debt amount (highest first)")

        await interaction.response.send_message(embed=embed)

    except Exception as e:
        print(f"Error in get_all_debt command: {e}")
        import traceback
        traceback.print_exc()
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred while fetching debts. Please try again.", ephemeral=True)
        else:
            await interaction.followup.send("❌ An error occurred while fetching debts. Please try again.", ephemeral=True)


# Run the bot with retry logic for rate limiting
async def run_bot_with_retry():
    """Run the bot with retry logic for Cloudflare rate limiting"""
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        print("Error: DISCORD_BOT_TOKEN environment variable not set!")
        print("Please set your Discord bot token as an environment variable.")
        return
    
    max_retries = 5
    retry_delay = 30  # Start with 30 seconds
    
    for attempt in range(max_retries):
        try:
            print(f"Attempting to start bot (attempt {attempt + 1}/{max_retries})...")
            await bot.start(token)
            break  # Success, exit retry loop
        except discord.HTTPException as e:
            if e.status == 429:
                # Rate limited by Cloudflare
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    print(f"⚠️ Rate limited by Cloudflare (Error 1015). Waiting {wait_time} seconds before retry...")
                    print(f"   This is common on Render. Discord's Cloudflare may temporarily block IPs.")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"❌ Failed to connect after {max_retries} attempts due to rate limiting.")
                    print(f"   Cloudflare is blocking this IP. This is usually temporary.")
                    print(f"   Solutions:")
                    print(f"   1. Wait 10-30 minutes and redeploy")
                    print(f"   2. Try a different hosting provider (Railway, Heroku, etc.)")
                    print(f"   3. Contact Discord support if the issue persists")
                    raise
            else:
                # Other HTTP errors
                print(f"❌ HTTP error {e.status}: {e}")
                raise
        except KeyboardInterrupt:
            print("\nBot is shutting down...")
            break
        except Exception as e:
            print(f"❌ Bot crashed with error: {e}")
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                print(f"   Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            else:
                raise


# Run the bot
if __name__ == "__main__":
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        print("Error: DISCORD_BOT_TOKEN environment variable not set!")
        print("Please set your Discord bot token as an environment variable.")
        exit(1)
    else:
        try:
            # Use asyncio.run for async retry logic
            asyncio.run(run_bot_with_retry())
        except KeyboardInterrupt:
            print("\nBot is shutting down...")
        except Exception as e:
            print(f"Bot crashed with error: {e}")
            # Don't raise - let the process exit gracefully
            exit(1)
