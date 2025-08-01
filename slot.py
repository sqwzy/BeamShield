import discord
from discord.ext import commands, tasks
import json
import os
import datetime
import pytz
import asyncio
import uuid

# Load configuration from config.json
with open('config.json', 'r') as f:
    CONFIG = json.load(f)

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="=", intents=intents, help_command=None)

# Category IDs for slot categories
CATEGORIES = {
    "elite": CONFIG["CATEGORY_1_ID"],
    "standard": CONFIG["CATEGORY_2_ID"],
    "trial": CONFIG["CATEGORY_2_ID"] # Assuming trial uses the same category as standard for now
}

# Ping limits per category (daily)
PING_LIMITS = {
    "elite": {"everyone": 1, "here": 2},
    "standard": {"everyone": 0, "here": 2},
    "trial": {"everyone": 0, "here": 1}
}

PING_RESET_ALERT_CHANNEL = CONFIG["PING_RESET_CHANNEL"]
ADMIN_LOG_CHANNEL = CONFIG["ADMIN_LOG_CHANNEL"]

SLOTS_FILE = "data/slots.json"
REVOKED_FILE = "data/revoked_slots.json"

# Ensure data folder and files exist
os.makedirs("data", exist_ok=True)
for file in [SLOTS_FILE, REVOKED_FILE]:
    if not os.path.exists(file):
        with open(file, "w") as f:
            json.dump({}, f)

def load_json(file):
    with open(file, "r") as f:
        return json.load(f)

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

def timestamp_embed(title, description, color):
    embed = discord.Embed(title=title, description=description, color=color)
    embed.timestamp = datetime.datetime.utcnow()
    return embed


class RecoveryModal(discord.ui.Modal, title="🔐 Tier Recovery • Slot Key"):
    recovery_key = discord.ui.TextInput(
        label="Private Slot Key",
        placeholder="Enter your unique slot recovery key here",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        entered_key = self.recovery_key.value.strip()
        slots = load_json(SLOTS_FILE)

        matched_uid = None
        for uid, slot in slots.items():
            if slot.get("recovery_key") == entered_key:
                matched_uid = uid
                break

        if not matched_uid:
            return await interaction.response.send_message(f"{CONFIG['EMOJIS']['cross']} Invalid or expired recovery key.", ephemeral=True)

        old_user = await bot.fetch_user(int(matched_uid))
        new_user = interaction.user

        if str(new_user.id) in slots:
            return await interaction.response.send_message(f"{CONFIG['EMOJIS']['warning']} You already own a slot.", ephemeral=True)

        channel = bot.get_channel(slots[matched_uid]["channel_id"])
        if not channel:
            return await interaction.response.send_message(f"{CONFIG['EMOJIS']['warning']} Slot channel not found.", ephemeral=True)

        await channel.set_permissions(old_user, overwrite=None)
        await channel.set_permissions(new_user, read_messages=True, send_messages=True, mention_everyone=True,
                                      embed_links=True, attach_files=True, use_external_emojis=True)

        try:
            old_msg = await channel.fetch_message(slots[matched_uid].get("welcome_msg_id"))
            await old_msg.delete()
        except:
            pass

        embed = slot_info_embed(slots[matched_uid], new_user, channel)
        view = CopyRecoveryKeyView(slots[matched_uid]["recovery_key"], new_user.id)
        new_welcome = await channel.send(embed=embed, view=view)


class PersistentRecoveryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Recover Slot", style=discord.ButtonStyle.green, emoji="🔐", custom_id="recover_slot_button")
    async def recover_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RecoveryModal())


async def self_destruct_message(message, countdown_time=10):
    """Add a self-destruct countdown to a message and delete it after countdown"""
    for i in range(countdown_time, 0, -1):
        try:
            embed = discord.Embed(
                description=f"This message will self destruct in **{i}** seconds",
                color=discord.Color.red()
            )
            embed.set_footer(text="⚠️ Auto-delete countdown")
            await message.edit(embed=embed)
            await asyncio.sleep(1)
        except:
            return
    
    try:
        await message.delete()
    except:
        pass

        # Remove old roles from previous owner
        guild = interaction.guild
        if plan == "standard":
            role_standard = guild.get_role(CONFIG["STANDARD_ROLE_ID"])
            role_elite = guild.get_role(CONFIG["ELITE_ROLE_ID"])
            if role_standard: await old_user.remove_roles(role_standard)
            if role_elite: await old_user.remove_roles(role_elite)
        elif plan == "elite":
            role_elite = guild.get_role(CONFIG["ELITE_ROLE_ID"])
            if role_elite: await old_user.remove_roles(role_elite)
        

        # Assign role
        plan = slots[matched_uid]["plan"]
        if plan == "standard":
            role = interaction.guild.get_role(CONFIG["STANDARD_ROLE_ID"])
        elif plan == "elite":
            role = interaction.guild.get_role(CONFIG["ELITE_ROLE_ID"])
        else:
            role = None
        if role:
            try:
                await new_user.add_roles(role)
            except:
                pass
        access_role = interaction.guild.get_role(CONFIG["ACCESS_ROLE_ID"])
        if access_role:
            try:
                await new_user.add_roles(access_role)
            except:
                pass

        # Rotate new key
        new_key = str(uuid.uuid4()).split("-")[0].upper()

        slots[str(new_user.id)] = slots.pop(matched_uid)
        slots[str(new_user.id)]["welcome_msg_id"] = new_welcome.id
        slots[str(new_user.id)]["recovery_key"] = new_key
        save_json(SLOTS_FILE, slots)

        await interaction.response.send_message(f"{CONFIG['EMOJIS']['tick_animated']} Slot successfully recovered!", ephemeral=True)
        await new_user.send(f"{CONFIG['EMOJIS']['tick_animated']} Your new recovery key: **||`{new_key}`||\nPlease save this securely.")

        log = bot.get_channel(ADMIN_LOG_CHANNEL)
        if log:
            await log.send(embed=timestamp_embed(
                "🔐 Slot Recovered",
                f"{new_user.mention} recovered slot from `{entered_key}`.",
                discord.Color.orange()
            ))


def ping_usage_embed(everyone_used, here_used, plan, custom_limits=None):
    limits = custom_limits if custom_limits else PING_LIMITS[plan]
    embed = discord.Embed(
        description=f"{CONFIG['EMOJIS']['correct/tick']} **Pings used:** *@everyone* `{everyone_used}/{limits['everyone']}` | *@here* `{here_used}/{limits['here']}`\n\n **Must use https://discord.com/channels/1381299988537282581/1381509144577839195 for secure purchases.**",
        color=discord.Color.blurple()
    )
    embed.set_footer(text=".gg/vexusfr | Ping Tracker")
    return embed

def slot_info_embed(slot_data, user, channel):
    limits = slot_data.get("custom_limits", PING_LIMITS[slot_data['plan']])
    start_dt = datetime.datetime.fromtimestamp(slot_data['start_ts'])
    end_dt = datetime.datetime.fromtimestamp(slot_data['end_ts'])
    
    # Calculate days until expiry
    now = datetime.datetime.utcnow()
    days_left = (end_dt - now).days
    
    embed = discord.Embed(
        title="**Slot created**",
        description="Thanks for choosing Vexus Slots!",
        color=0xFF8C00  # Orange color
    )
    
    # Owner and Expires side by side
    embed.add_field(
        name="Owner:",
        value=user.mention,
        inline=True
    )
    
    embed.add_field(
        name="Expires:",
        value=f"In **{days_left}** days",
        inline=True
    )
    
    # Slot ID
    embed.add_field(
        name="Slot:",
        value=f"#{channel.name if channel else 'Unknown'}",
        inline=True
    )
    
    # Allowed pings and Purchase Date side by side
    ping_text = f"{limits['here']}x here {limits['everyone']}x everyone"
    embed.add_field(
        name="Allowed pings:",
        value=ping_text,
        inline=True
    )
    
    embed.add_field(
        name="Purchase Date:",
        value=start_dt.strftime("%B %d, %Y"),
        inline=True
    )
    
    # Add empty field for spacing
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    
    # Recovery key section
    embed.add_field(
        name="Users recovery key",
        value=f"||**`{slot_data['recovery_key']}`**||",
        inline=False
    )
    
    embed.set_footer(text="Created By Vexus Slots")
    return embed


class CopyRecoveryKeyView(discord.ui.View):
    def __init__(self, recovery_key, user_id):
        super().__init__(timeout=None)
        self.recovery_key = recovery_key
        self.user_id = user_id

    @discord.ui.button(label="Copy Recovery Key", style=discord.ButtonStyle.gray, emoji="🔐", custom_id="copy_recovery_key")
    async def copy_recovery_key(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                f"{CONFIG['EMOJIS']['cross']} You can only copy your own recovery key.",
                ephemeral=True
            )
        
        try:
            await interaction.user.send(f"🔐 **Your Recovery Key:** ||**`{self.recovery_key}`**||")
            await interaction.response.send_message(
                f"{CONFIG['EMOJIS']['tick']} Recovery key sent to your DMs!",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                f"{CONFIG['EMOJIS']['cross']} Could not send DM. Please enable DMs from server members.",
                ephemeral=True
            )

def parse_duration(duration: int, unit: str) -> int:
    unit = unit.lower()
    if unit == "d":
        return duration * 86400
    elif unit == "m":
        return duration * 2592000  # 30 days approx
    elif unit == "min":
        return duration * 60
    else:
        raise ValueError("Invalid duration unit. Use 'd', 'm', or 'min'.")

async def dm_user(user: discord.User, title: str, message: str, color=discord.Color.blue()):
    try:
        embed = discord.Embed(title=title, description=message, color=color)
        await user.send(embed=embed)
    except discord.Forbidden:
        # User DMs disabled or blocked bot
        pass


@bot.event
async def on_ready():
    print(f"{CONFIG['EMOJIS']['tick']} Logged in as {bot.user} ({bot.user.id})")

    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=".gg/vexusfr"))

    # Add persistent views
    bot.add_view(PersistentRecoveryView())

    check_expired_slots.start()
    daily_ping_reset.start()
    check_expiry_warnings.start()
    

    
@bot.command()
@commands.has_permissions(administrator=True)
async def create(ctx, user: discord.Member, duration: int, unit: str, plan: str, *, slot_name: str):
    plan = plan.lower()
    if plan not in CATEGORIES:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} Invalid plan/category. Choose from: {', '.join(CATEGORIES.keys())}", color=discord.Color.red()))

    try:
        dur_seconds = parse_duration(duration, unit)
    except ValueError as e:
        return await ctx.send(embed=discord.Embed(description=str(e), color=discord.Color.red()))

    slots = load_json(SLOTS_FILE)
    revoked = load_json(REVOKED_FILE)

    # Prevent duplicate slots per user
    if str(user.id) in slots:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} User already has an active slot.", color=discord.Color.red()))

    # Create channel overwrites
    guild = ctx.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),  # Hide for everyone by default
        user: discord.PermissionOverwrite(
            read_messages=True, send_messages=True, mention_everyone=True,
            embed_links=True, attach_files=True, use_external_emojis=True
        ),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.get_role(CONFIG["EVERYONE_ROLE_ID"]): discord.PermissionOverwrite(read_messages=False),  # HiddenRole can't view
        guild.get_role(CONFIG["MEMBER_ROLE_ID"]): discord.PermissionOverwrite(read_messages=True, send_messages=False),  # VisibleRole can view only
    }


    category = guild.get_channel(CATEGORIES[plan])
    if not category:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} Category ID for `{plan}` not found.", color=discord.Color.red()))

    
    channel_name = f"ᯓ・{slot_name}".lower().replace(" ", "-")

    channel = await guild.create_text_channel(channel_name, overwrites=overwrites, category=category)
        # Assign roles based on plan
    try:
        if plan == "standard":
            role_standard = guild.get_role(CONFIG["STANDARD_ROLE_ID"])
            if role_standard:
                await user.add_roles(role_standard)
        elif plan == "elite":
            role_elite = guild.get_role(CONFIG["ELITE_ROLE_ID"])
            if role_elite:
                await user.add_roles(role_elite)
        access_role = guild.get_role(CONFIG["ACCESS_ROLE_ID"])
        if access_role:
            await user.add_roles(access_role)
    except Exception as e:
        print(f"[Role Assignment Error] Could not assign role(s) to {user}: {e}")



    now_ts = int(datetime.datetime.utcnow().timestamp())
    end_ts = now_ts + dur_seconds

    # Save slot data
    slots[str(user.id)] = {
        "recovery_key": str(uuid.uuid4()).split("-")[0].upper(),
        "channel_id": channel.id,
        "start_ts": now_ts,
        "end_ts": end_ts,
        "plan": plan,
        "everyone_used": 0,
        "here_used": 0,
        "held": False,
        "welcome_msg_id": None,
        "sticky_msg_id": None
    }
    save_json(SLOTS_FILE, slots)
    await dm_user(
        user,
        "🔐 Your Recovery Key",
        f"||**`{slots[str(user.id)]['recovery_key']}`**||\nKeep this key safe! It's your only way to recover your slot.",
        color=discord.Color.green()
    )


    # Send welcome embed with timestamps and Copy Recovery Key button
    embed = slot_info_embed(slots[str(user.id)], user, channel)
    view = CopyRecoveryKeyView(slots[str(user.id)]["recovery_key"], user.id)
    welcome_msg = await channel.send(embed=embed, view=view)
    slots[str(user.id)]["welcome_msg_id"] = welcome_msg.id
    save_json(SLOTS_FILE, slots)

    # Send confirmation to ctx
    await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['tick']} Slot created for {user.mention} in {channel.mention}", color=discord.Color.green()))

    # Log creation in admin channel
    log_chan = bot.get_channel(ADMIN_LOG_CHANNEL)
    if log_chan:
        await log_chan.send(embed=timestamp_embed(
            f"{CONFIG['EMOJIS']['correct/tick']} Slot Created",
            f"Slot `{channel.name}` created for {user.mention} by {ctx.author.mention}\nPlan: {plan.title()}\nExpires: <t:{end_ts}:F>",
            discord.Color.green()
        ))

@bot.command()
async def nuke(ctx, user: discord.Member = None):
    # If no user specified, use command author
    if user is None:
        user = ctx.author
    
    uid = str(user.id)
    slots = load_json(SLOTS_FILE)

    # Check if user has permission or owns the slot
    if not ctx.author.guild_permissions.administrator and str(ctx.author.id) != uid:
        return await ctx.send(embed=discord.Embed(
            description=f"{CONFIG['EMOJIS']['cross']} You can only nuke your own slot.",
            color=discord.Color.red()
        ))

    if uid not in slots:
        return await ctx.send(embed=discord.Embed(
            description=f"{CONFIG['EMOJIS']['cancel/cross']} This user does not have an active slot.",
            color=discord.Color.red()
        ))

    slot = slots[uid]
    channel = bot.get_channel(slot['channel_id'])
    if not channel:
        return await ctx.send(embed=discord.Embed(
            description=f"{CONFIG['EMOJIS']['cancel/cross']} Slot channel not found.",
            color=discord.Color.red()
        ))

    try:
        # Purge all messages
        await channel.purge(limit=1000)

        # Reset ping usage
        slot["everyone_used"] = 0
        slot["here_used"] = 0
        
        # Send new welcome message
        embed = slot_info_embed(slot, user, channel)
        view = CopyRecoveryKeyView(slot["recovery_key"], user.id)
        welcome_msg = await channel.send(embed=embed, view=view)
        slot["welcome_msg_id"] = welcome_msg.id
        
        # Send new ping tracker
        ping_embed = ping_usage_embed(0, 0, slot["plan"], slot.get("custom_limits"))
        ping_msg = await channel.send(embed=ping_embed)
        slot["sticky_msg_id"] = ping_msg.id
        
        save_json(SLOTS_FILE, slots)

        if ctx.channel != channel:
            await ctx.send(embed=discord.Embed(
                description=f"{CONFIG['EMOJIS']['tick']} Successfully nuked and reset slot for {user.mention}.",
                color=discord.Color.green()
            ))

        await channel.send(embed=discord.Embed(
            description=f"{CONFIG['EMOJIS']['warning']} This slot was nuked and reset by {ctx.author.mention}.",
            color=discord.Color.blurple()
        ))

    except Exception as e:
        await ctx.send(embed=discord.Embed(
            description=f"{CONFIG['EMOJIS']['cancel/cross']} Failed to nuke: `{str(e)}`",
            color=discord.Color.red()
        ))


@bot.command()
@commands.has_permissions(administrator=True)
async def sendrecoverypanel(ctx):
    embed = discord.Embed(
        title=f"{CONFIG['EMOJIS']['staff']} Tier Recovery System",
        description="If you've lost access to your channel, you can use your **Private Recovery Key** to initiate a recovery.\n\n**Click the button below to begin the process.**",
        color=discord.Color.green()
    )
    embed.set_footer(text="Elite Key System • Recovery Panel")
    await ctx.send(embed=embed, view=PersistentRecoveryView())



@bot.command()
@commands.has_permissions(administrator=True)
async def revoke(ctx, user: discord.Member, *, reason: str = "No reason provided"):
    slots = load_json(SLOTS_FILE)
    revoked = load_json(REVOKED_FILE)

    uid = str(user.id)
    if uid not in slots:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} No active slot found for {user.mention}.", color=discord.Color.red()))

    slot = slots[uid]
        # Remove roles based on plan
    try:
        if slot["plan"] == "standard":
            role1 = ctx.guild.get_role(CONFIG["STANDARD_ROLE_ID"])
            role2 = ctx.guild.get_role(CONFIG["ELITE_ROLE_ID"])
            if role1: await user.remove_roles(role1)
            if role2: await user.remove_roles(role2)
        elif slot["plan"] == "elite":
            role = ctx.guild.get_role(CONFIG["ELITE_ROLE_ID"])
            if role: await user.remove_roles(role)
    except Exception as e:
        print(f"[Role Removal Error] Could not remove roles from {user}: {e}")

    channel = bot.get_channel(slot['channel_id'])
    if not channel:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} Slot channel not found.", color=discord.Color.red()))

    # Set permissions: hide from everyone, read-only for user
    # Reset permissions
    await channel.set_permissions(ctx.guild.default_role, overwrite=None)
    await channel.set_permissions(user, overwrite=None)
    await channel.set_permissions(ctx.guild.me, read_messages=True, send_messages=True)

    # Deny access to specific roles
    role_hidden = ctx.guild.get_role(CONFIG["EVERYONE_ROLE_ID"])
    role_visible = ctx.guild.get_role(CONFIG["MEMBER_ROLE_ID"])
    if role_hidden:
        await channel.set_permissions(role_hidden, read_messages=False)
    if role_visible:
        await channel.set_permissions(role_visible, read_messages=False)

    # Allow only staff role and admins
    admin_role = discord.utils.get(ctx.guild.roles, permissions=discord.Permissions(administrator=True))
    staff_role = ctx.guild.get_role(CONFIG["STAFF_ROLE_ID"])
    if admin_role:
        await channel.set_permissions(admin_role, read_messages=True)
    if staff_role:
        await channel.set_permissions(staff_role, read_messages=True)

    # Move channel to revoked category
    revoked_category = ctx.guild.get_channel(CONFIG["REVOKED_SLOT_CATEGORY_ID"])
    if revoked_category:
        await channel.edit(category=revoked_category) #here



    # Send revoke message in slot channel
    await channel.send(embed=timestamp_embed(
        f"{CONFIG['EMOJIS']['cancel/cross']} Slot Revoked",
        f"Your slot has been revoked by staff.\n\nReason: {reason}",
        discord.Color.red()
    ))

    # DM user about revocation
    await dm_user(user, f"{CONFIG['EMOJIS']['cancel/cross']} Slot Revoked", f"Your slot has been revoked.\nReason: {reason}", discord.Color.red())

    # Move slot data to revoked file
    revoked[uid] = slot
    save_json(REVOKED_FILE, revoked)

    # Remove from active slots
    slots.pop(uid)
    save_json(SLOTS_FILE, slots)

    # Log in admin channel with who revoked
    log_chan = bot.get_channel(ADMIN_LOG_CHANNEL)
    if log_chan:
        await log_chan.send(embed=timestamp_embed(
            f"{CONFIG['EMOJIS']['error']} Slot Revoked (Manual)",
            f"Slot for {user.mention} revoked by {ctx.author.mention}\nReason: {reason}",
            discord.Color.red()
        ))

    await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['tick']} Slot revoked for {user.mention}.", color=discord.Color.green()))

@bot.command()
@commands.has_permissions(administrator=True)
async def restore(ctx, user: discord.Member):
    revoked = load_json(REVOKED_FILE)
    slots = load_json(SLOTS_FILE)
    uid = str(user.id)

    if uid not in revoked:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} No revoked slot found for {user.mention}.", color=discord.Color.red()))

    slot = revoked[uid]
    channel = bot.get_channel(slot["channel_id"])
    if not channel:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} Slot channel not found.", color=discord.Color.red()))

    slot['everyone_used'] = 0
    slot['here_used'] = 0

    # Restore permissions: allow user to send & mention, default_role can read but not send
    # Reset permissions to default per-plan structure
    # Reset permissions to default per-plan structure
    await channel.set_permissions(ctx.guild.default_role, read_messages=False)

    await channel.set_permissions(user, read_messages=True, send_messages=True, mention_everyone=True,
        embed_links=True, attach_files=True, use_external_emojis=True)

    await channel.set_permissions(ctx.guild.me, read_messages=True, send_messages=True)

    # Update special roles' visibility
    role_hidden = ctx.guild.get_role(CONFIG["EVERYONE_ROLE_ID"])
    role_visible = ctx.guild.get_role(CONFIG["MEMBER_ROLE_ID"])
    if role_hidden:
        await channel.set_permissions(role_hidden, read_messages=False)
    if role_visible:
        await channel.set_permissions(role_visible, read_messages=True, send_messages=False)


    # Restore correct category
    target_category_id = CATEGORIES.get(slot["plan"])
    category = ctx.guild.get_channel(target_category_id)
    if category:
        await channel.edit(category=category)

    # Reassign correct user role
    try:
        if slot["plan"] == "standard":
            role_standard = ctx.guild.get_role(CONFIG["STANDARD_ROLE_ID"])
            if role_standard and role_standard not in user.roles:
                await user.add_roles(role_standard)
        elif slot["plan"] == "elite":
            role_elite = ctx.guild.get_role(CONFIG["ELITE_ROLE_ID"])
            if role_elite and role_elite not in user.roles:
                await user.add_roles(role_elite)
    except Exception as e:
        print(f"[Restore Role Error] Couldn't reassign role to {user}: {e}")


    # Move back to active slots
    slots[uid] = slot
    save_json(SLOTS_FILE, slots)

    revoked.pop(uid)
    save_json(REVOKED_FILE, revoked)

    await channel.send(embed=timestamp_embed(f"{CONFIG['EMOJIS']['tick']} Slot Restored", f"Slot for {user.mention} has been restored and is now active.", discord.Color.green()))
    await dm_user(user, f"{CONFIG['EMOJIS']['tick']} Slot Restored", "Your slot has been restored and reactivated.", discord.Color.green())

    # Log restore in admin channel
    log_chan = bot.get_channel(ADMIN_LOG_CHANNEL)
    if log_chan:
        await log_chan.send(embed=timestamp_embed(
            f"{CONFIG['EMOJIS']['refresh']} Slot Restored",
            f"Slot for {user.mention} restored by {ctx.author.mention}",
            discord.Color.green()
        ))

    await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['tick']} Slot restored for {user.mention}.", color=discord.Color.green()))

@bot.command()
@commands.has_permissions(administrator=True)
async def hold(ctx, user: discord.Member, *, reason: str):
    slots = load_json(SLOTS_FILE)
    uid = str(user.id)

    if uid not in slots:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} No active slot found for {user.mention}.", color=discord.Color.red()))
    slot = slots[uid]

    if slot.get("held"):
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['warning']} Slot for {user.mention} is already held.", color=discord.Color.orange()))

    channel = bot.get_channel(slot["channel_id"])
    if not channel:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} Slot channel not found.", color=discord.Color.red()))

    # Remove send perms for user
    await channel.set_permissions(user, send_messages=False)

    # Add on-hold role if configured
    if CONFIG["ON_HOLD_ROLE_ID"] != 0:
        hold_role = ctx.guild.get_role(CONFIG["ON_HOLD_ROLE_ID"])
        if hold_role:
            try:
                await user.add_roles(hold_role)
            except:
                pass

    slot["held"] = True
    save_json(SLOTS_FILE, slots)

    await channel.send(embed=timestamp_embed(f"{CONFIG['EMOJIS']['error']} Slot Held", f"Slot is held.\nReason: {reason}", discord.Color.red()))
    await dm_user(user, f"{CONFIG['EMOJIS']['error']} Slot Held", f"Your slot has been put on hold.\nReason: {reason}", discord.Color.red())

    # Log hold in admin channel
    log_chan = bot.get_channel(ADMIN_LOG_CHANNEL)
    if log_chan:
        await log_chan.send(embed=timestamp_embed(
            f"{CONFIG['EMOJIS']['error']} Slot Held",
            f"Slot for {user.mention} held by {ctx.author.mention}\nReason: {reason}",
            discord.Color.orange()
        ))

    await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['tick']} Slot held for {user.mention}.", color=discord.Color.green()))

@bot.command()
@commands.has_permissions(administrator=True)
async def genslotkey(ctx):
    slots = load_json(SLOTS_FILE)
    success_count = 0
    failed_users = []

    for uid in slots:
        try:
            slot_data = slots[uid]  # Always fetch fresh reference

            # Generate key if missing
            if "recovery_key" not in slot_data or not slot_data["recovery_key"]:
                slot_data["recovery_key"] = str(uuid.uuid4()).split("-")[0].upper()

            user = await bot.fetch_user(int(uid))
            await dm_user(
                user,
                "🔐 Your Recovery Key",
                f"||**`{slot_data['recovery_key']}`**||\nKeep this key safe! It's your only way to recover your slot.",
                color=discord.Color.green()
            )
            success_count += 1

        except Exception as e:
            failed_users.append(uid)

    save_json(SLOTS_FILE, slots)  # Save new keys!

    await ctx.send(embed=discord.Embed(
        description=f"{CONFIG['EMOJIS']['tick']} Sent recovery keys to **{success_count}** users.\n"
                    f"{CONFIG['EMOJIS']['cross']} Failed to send to `{len(failed_users)}` users (DMs off or blocked).",
        color=discord.Color.green()
    ))




@bot.command()
@commands.has_permissions(administrator=True)
async def unhold(ctx, user: discord.Member):
    slots = load_json(SLOTS_FILE)
    uid = str(user.id)

    if uid not in slots:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} No active slot found for {user.mention}.", color=discord.Color.red()))
    slot = slots[uid]

    if not slot.get("held"):
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['warning']} Slot for {user.mention} is not held.", color=discord.Color.orange()))

    channel = bot.get_channel(slot["channel_id"])
    if not channel:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} Slot channel not found.", color=discord.Color.red()))

    # Restore send perms for user
    await channel.set_permissions(user, send_messages=True)

    # Remove on-hold role if configured
    if CONFIG["ON_HOLD_ROLE_ID"] != 0:
        hold_role = ctx.guild.get_role(CONFIG["ON_HOLD_ROLE_ID"])
        if hold_role:
            try:
                await user.remove_roles(hold_role)
            except:
                pass

    slot["held"] = False
    save_json(SLOTS_FILE, slots)

    await channel.send(embed=timestamp_embed(f"{CONFIG['EMOJIS']['tick']} Slot Unheld", "Slot hold removed. You may continue using your slot.", discord.Color.green()))
    await dm_user(user, f"{CONFIG['EMOJIS']['tick']} Slot Unheld", "Your slot hold has been lifted. You may now continue using it.", discord.Color.green())

    # Log unhold in admin channel
    log_chan = bot.get_channel(ADMIN_LOG_CHANNEL)
    if log_chan:
        await log_chan.send(embed=timestamp_embed(
            f"{CONFIG['EMOJIS']['arrow']} Slot Unheld",
            f"Slot for {user.mention} unheld by {ctx.author.mention}",
            discord.Color.green()
        ))

    await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['tick']} Slot unheld for {user.mention}.", color=discord.Color.green()))

@bot.command()
async def pings(ctx):
    slots = load_json(SLOTS_FILE)
    uid = str(ctx.author.id)

    if uid not in slots:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} You do not own an active slot.", color=discord.Color.red()))
    slot = slots[uid]

    embed = ping_usage_embed(slot["everyone_used"], slot["here_used"], slot["plan"], slot.get("custom_limits"))
    await ctx.send(embed=embed)
    
@bot.command()
async def slotinfo(ctx, user: discord.Member = None):
    if user is None:
        user = ctx.author
    slots = load_json(SLOTS_FILE)
    uid = str(user.id)

    if uid not in slots:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} This user does not have an active slot.", color=discord.Color.red()))
    slot = slots[uid]
    channel = bot.get_channel(slot["channel_id"])
    embed = slot_info_embed(slot, user, channel)
    await ctx.send(embed=embed)

@tasks.loop(seconds=60)
async def check_expired_slots():
    slots = load_json(SLOTS_FILE)
    revoked = load_json(REVOKED_FILE)
    now_ts = int(datetime.datetime.utcnow().timestamp())
    to_revoke = []

    for uid, slot in slots.items():
        if not slot.get("held", False) and now_ts > slot["end_ts"]:
            to_revoke.append(uid)

    for uid in to_revoke:
        slot = slots[uid]
        channel = bot.get_channel(slot["channel_id"])
        user = bot.get_user(int(uid))

        if channel and user:
            await channel.set_permissions(channel.guild.default_role, read_messages=False)
            await channel.set_permissions(user, read_messages=True, send_messages=False)
            await channel.send(embed=timestamp_embed(
                f"{CONFIG['EMOJIS']['cancel/cross']} Slot Expired",
                "Your slot has expired. Contact staff for renewal.",
                discord.Color.dark_gray()
            ))

            await dm_user(user,
                f"{CONFIG['EMOJIS']['cancel/cross']} Slot Expired",
                "Your slot on **Slotify** has expired. Contact staff to renew.",
                discord.Color.dark_gray()
            )

            log_chan = bot.get_channel(ADMIN_LOG_CHANNEL)
            if log_chan:
                await log_chan.send(embed=timestamp_embed(
                    f"{CONFIG['EMOJIS']['cancel/cross']} Slot Expired",
                    f"Slot for {user.mention} auto-expired.",
                    discord.Color.dark_gray()
                ))

        revoked[uid] = slot
        slots.pop(uid)

    save_json(SLOTS_FILE, slots)
    save_json(REVOKED_FILE, revoked)


@tasks.loop(minutes=60)
async def check_expiry_warnings():
    slots = load_json(SLOTS_FILE)
    now_ts = int(datetime.datetime.utcnow().timestamp())
    warning_threshold = 24 * 3600  # 24 hours in seconds
    warned_users = []

    for uid, slot in slots.items():
        end_ts = slot.get("end_ts", 0)
        if end_ts - now_ts <= warning_threshold and end_ts - now_ts > 0:
            # Skip already warned slots
            if slot.get("warned", False):
                continue

            user = await bot.fetch_user(int(uid))
            channel = bot.get_channel(slot['channel_id'])
            if not channel or not user:
                continue

            # Send warning in slot channel
            await channel.send(embed=timestamp_embed(
                f"{CONFIG['EMOJIS']['warning']} Slot Expiry Warning",
                f"{user.mention}, your slot will expire in less than 24 hours.\nPlease contact the staff to renew.",
                discord.Color.orange()
            ))

            # Send DM warning
            await dm_user(
                user,
                f"{CONFIG['EMOJIS']['warning']} Slot Expiry Warning",
                "Your slot will expire in less than 24 hours. Contact staff if you'd like to renew.",
                discord.Color.orange()
            )

            # Log in admin channel
            log_channel = bot.get_channel(ADMIN_LOG_CHANNEL)
            if log_channel:
                await log_channel.send(embed=timestamp_embed(
                    f"{CONFIG['EMOJIS']['warning']} Expiry Warning Sent",
                    f"Sent expiry warning to {user.mention} (`{user.id}`) — {channel.mention}",
                    discord.Color.orange()
                ))

            slot["warned"] = True
            warned_users.append(uid)

    if warned_users:
        save_json(SLOTS_FILE, slots)


@tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=pytz.timezone('Europe/Amsterdam')))
async def daily_ping_reset():
    slots = load_json(SLOTS_FILE)
    for uid, slot in slots.items():
        slot["everyone_used"] = 0
        slot["here_used"] = 0
        channel = bot.get_channel(slot["channel_id"])
        if not channel:
            continue

        try:
            def preserve(msg):
                return msg.id == slot.get("welcome_msg_id")
            await channel.purge(limit=1000, check=lambda m: not preserve(m))
        except Exception:
            pass

        try:
            embed = ping_usage_embed(0, 0, slot["plan"], slot.get("custom_limits"))
            msg = await channel.send(embed=embed)
            slot["sticky_msg_id"] = msg.id
        except Exception:
            pass

    save_json(SLOTS_FILE, slots)

    alert_chan = bot.get_channel(PING_RESET_ALERT_CHANNEL)
    if alert_chan:
        # Delete the old reset message if it exists
        try:
            async for message in alert_chan.history(limit=50):
                if message.author == bot.user and message.embeds:
                    embed = message.embeds[0]
                    if embed.title and "Ping Reset" in embed.title:
                        await message.delete()
                        break
        except Exception:
            pass
        
        # First ping the role so it gets notified
        await alert_chan.send(f"<@&{CONFIG['ACCESS_ROLE_ID']}>")  # Role mention outside embed
        
        # Send new reset message
        await alert_chan.send(embed=timestamp_embed(
            "> **Ping Reset**",
            "-# All slot ping counters have been reset and messages purged.",
            discord.Color.blurple()
        ))

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Auto-react to messages in suggestion channel
    if CONFIG["SUGGESTION_CHANNEL_ID"] != 0 and message.channel.id == CONFIG["SUGGESTION_CHANNEL_ID"]:
        try:
            await message.add_reaction("👍")
            await message.add_reaction("👎")
        except:
            pass

    slots = load_json(SLOTS_FILE)
    uid = str(message.author.id)

    if uid in slots:
        slot = slots[uid]
        if message.channel.id == slot["channel_id"]:
            if message.author.id != int(uid):
                # Non-owner message - ignore
                return

            # Check if slot is held: block sending messages
            if slot.get("held", False):
                try:
                    await message.delete()
                except:
                    pass
                return

            # Check ping abuse:
            content_lower = message.content.lower()
            used_ping = False
            limits = slot.get("custom_limits", PING_LIMITS[slot["plan"]])

            # Only count exact mentions (case-insensitive)
            if "@everyone" in message.content:
                slot["everyone_used"] += 1
                used_ping = True
            if "@here" in message.content:
                slot["here_used"] += 1
                used_ping = True

            # Revoke slot if over limit
            if slot["everyone_used"] > limits["everyone"] or slot["here_used"] > limits["here"]:
                channel = message.channel
                user = message.author

                # Revoke permissions
                await channel.set_permissions(channel.guild.default_role, overwrite=None)
                await channel.set_permissions(user, overwrite=None)
                await channel.set_permissions(channel.guild.me, read_messages=True, send_messages=True)

                # Deny HiddenRole and VisibleRole
                role_hidden = channel.guild.get_role(CONFIG["EVERYONE_ROLE_ID"])
                role_visible = channel.guild.get_role(CONFIG["MEMBER_ROLE_ID"])
                if role_hidden:
                    await channel.set_permissions(role_hidden, read_messages=False)
                if role_visible:
                    await channel.set_permissions(role_visible, read_messages=False)

                # Allow only staff and admins
                admin_role = discord.utils.get(channel.guild.roles, permissions=discord.Permissions(administrator=True))
                staff_role = channel.guild.get_role(CONFIG["STAFF_ROLE_ID"])
                if admin_role:
                    await channel.set_permissions(admin_role, read_messages=True)
                if staff_role:
                    await channel.set_permissions(staff_role, read_messages=True)

                # Move to revoked category
                revoked_category = channel.guild.get_channel(CONFIG["REVOKED_SLOT_CATEGORY_ID"])
                if revoked_category:
                    await channel.edit(category=revoked_category) #here



                # Move slot to revoked
                revoked = load_json(REVOKED_FILE)
                revoked[uid] = slot
                save_json(REVOKED_FILE, revoked)

                slots.pop(uid)
                save_json(SLOTS_FILE, slots)

                await channel.send(embed=timestamp_embed(
                    f"{CONFIG['EMOJIS']['cancel/cross']} Slot Revoked",
                    "Your slot was auto-revoked for ping abuse.",
                    discord.Color.red()
                ))
                await dm_user(user, f"{CONFIG['EMOJIS']['cancel/cross']} Slot Revoked", "Your slot was revoked due to ping abuse.", discord.Color.red())

                log_chan = bot.get_channel(ADMIN_LOG_CHANNEL)
                if log_chan:
                    await log_chan.send(embed=timestamp_embed(
                        f"{CONFIG['EMOJIS']['warning']} Auto Revoke",
                        f"Slot for {user.mention} auto-revoked for ping abuse.",
                        discord.Color.red()
                    ))
                return

            if used_ping:
                # Delete old sticky ping usage message if exists
                try:
                    channel = message.channel
                    if "sticky_msg_id" in slot:
                        old_msg = await channel.fetch_message(slot["sticky_msg_id"])
                        await old_msg.delete()
                except:
                    pass

                # Send ping usage embed
                embed = ping_usage_embed(slot["everyone_used"], slot["here_used"], slot["plan"], slot.get("custom_limits"))
                msg = await message.channel.send(embed=embed)
                slot["sticky_msg_id"] = msg.id
                save_json(SLOTS_FILE, slots)
                
                # Send self-destruct notification
                self_destruct_embed = discord.Embed(
                    title="Ping Used",
                    description=f"Ping used by {message.author.mention}",
                    color=discord.Color.orange()
                )
                self_destruct_msg = await message.channel.send(embed=self_destruct_embed)
                
                # Start countdown in background
                asyncio.create_task(self_destruct_message(self_destruct_msg, 10))

    await bot.process_commands(message)

@bot.command()
@commands.has_permissions(administrator=True)
async def transfer(ctx, old_user: discord.Member, new_user: discord.Member):
    slots = load_json(SLOTS_FILE)
    uid_old = str(old_user.id)
    uid_new = str(new_user.id)

    if uid_old not in slots:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} The source user does not have an active slot.", color=discord.Color.red()))
    
    if uid_new in slots:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} The target user already has an active slot.", color=discord.Color.red()))

    slot = slots[uid_old]
    channel = bot.get_channel(slot['channel_id'])

    if not channel:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} Slot channel not found.", color=discord.Color.red()))

    # Update channel permissions
    await channel.set_permissions(old_user, overwrite=None)
    await channel.set_permissions(new_user, read_messages=True, send_messages=True, mention_everyone=True,
                                  embed_links=True, attach_files=True, use_external_emojis=True)

    # Update slot JSON
    slots[uid_new] = slot
    del slots[uid_old]

    # Update welcome message with new embed
    try:
        welcome_msg_id = slot.get("welcome_msg_id")
        if welcome_msg_id:
            old_msg = await channel.fetch_message(welcome_msg_id)
            await old_msg.delete()
    except:
        pass

    new_welcome = await channel.send(embed=slot_info_embed(slot, new_user, channel))
    slot["welcome_msg_id"] = new_welcome.id

    save_json(SLOTS_FILE, slots)

    # DM Users
    await dm_user(old_user, f"{CONFIG['EMOJIS']['refresh']} Slot Transferred", f"Your slot has been transferred to {new_user.mention}.", discord.Color.orange())
    await dm_user(new_user, f"{CONFIG['EMOJIS']['refresh']} Slot Received", f"A slot has been transferred to you by the staff team.\nYou may now start using it.", discord.Color.green())

    # Channel confirmation
    await channel.send(embed=timestamp_embed(f"{CONFIG['EMOJIS']['refresh']} Slot Transferred", f"Ownership has been transferred to {new_user.mention}.", discord.Color.blurple()))

    # Admin log
    log_chan = bot.get_channel(ADMIN_LOG_CHANNEL)
    if log_chan:
        await log_chan.send(embed=timestamp_embed(
            f"{CONFIG['EMOJIS']['refresh']} Slot Transferred",
            f"Slot from {old_user.mention} transferred to {new_user.mention} by {ctx.author.mention}.",
            discord.Color.blurple()
        ))

    await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['tick']} Slot transferred from {old_user.mention} to {new_user.mention}.", color=discord.Color.green()))
    
@bot.command()
@commands.has_permissions(administrator=True)
async def rename(ctx, user: discord.Member, *, new_name: str):
    slots = load_json(SLOTS_FILE)
    uid = str(user.id)

    if uid not in slots:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} User does not have an active slot.", color=discord.Color.red()))

    slot = slots[uid]
    channel = bot.get_channel(slot["channel_id"])

    if not channel:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} Slot channel not found.", color=discord.Color.red()))

    new_name = new_name.lower().replace(" ", "-")
    await channel.edit(name=new_name)

    await channel.send(embed=timestamp_embed(f"{CONFIG['EMOJIS']['rename/pencil']} Slot Renamed", f"Slot has been renamed to `{new_name}` by staff.", discord.Color.orange()))
    await dm_user(user, f"{CONFIG['EMOJIS']['rename/pencil']} Slot Renamed", f"Your slot has been renamed to `{new_name}` by the staff.", discord.Color.orange())

    await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['tick']} Renamed slot for {user.mention} to `{new_name}`.", color=discord.Color.green()))
    
@bot.command()
@commands.has_permissions(administrator=True)
async def move(ctx, user: discord.Member, new_plan: str):
    new_plan = new_plan.lower()
    if new_plan not in CATEGORIES:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} Invalid plan. Choose from: prime, blaze, trail", color=discord.Color.red()))

    slots = load_json(SLOTS_FILE)
    uid = str(user.id)

    if uid not in slots:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} User does not have an active slot.", color=discord.Color.red()))

    slot = slots[uid]
    channel = bot.get_channel(slot["channel_id"])
    new_category = ctx.guild.get_channel(CATEGORIES[new_plan])

    if not channel or not new_category:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} Channel or new category not found.", color=discord.Color.red()))

    await channel.edit(category=new_category)
    slot["plan"] = new_plan
    save_json(SLOTS_FILE, slots)

    await channel.send(embed=timestamp_embed(f"{CONFIG['EMOJIS']['refresh']} Slot Moved", f"Your slot has been moved to `{new_plan.title()}` plan.", discord.Color.blurple()))
    await dm_user(user, f"{CONFIG['EMOJIS']['refresh']} Slot Moved", f"Your slot has been moved to `{new_plan.title()}` plan by staff.", discord.Color.blurple())

    await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['tick']} Moved slot of {user.mention} to `{new_plan.title()}`.", color=discord.Color.green()))
    
@bot.command()
async def timeleft(ctx):
    slots = load_json(SLOTS_FILE)
    uid = str(ctx.author.id)

    if uid not in slots:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} You don't own an active slot.", color=discord.Color.red()))

    slot = slots[uid]
    now = int(datetime.datetime.utcnow().timestamp())
    end = slot["end_ts"]
    seconds_left = end - now

    if seconds_left <= 0:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} Your slot has already expired.", color=discord.Color.red()))

    delta = datetime.timedelta(seconds=seconds_left)
    embed = discord.Embed(
        title="⏳ Time Left",
        description=f"Your slot will expire in **{str(delta)}**.",
        color=discord.Color.orange()
    )
    embed.set_footer(text=".gg/vexusfr | Time Tracker")
    await ctx.send(embed=embed)
    
@bot.command()
@commands.has_permissions(administrator=True)
async def slotstats(ctx):
    slots = load_json(SLOTS_FILE)
    revoked = load_json(REVOKED_FILE)

    total_active = len(slots)
    total_revoked = len(revoked)

    plan_counts = {"elite": 0, "standard": 0, "trial": 0}
    for slot in slots.values():
        plan = slot.get("plan")
        if plan in plan_counts:
            plan_counts[plan] += 1

    embed = discord.Embed(
        title="📊 Slot Statistics",
        color=discord.Color.blurple()
    )
    embed.add_field(name="Active Slots", value=f"`{total_active}`", inline=True)
    embed.add_field(name="Revoked Slots", value=f"`{total_revoked}`", inline=True)
    embed.add_field(name="—", value="—", inline=True)
    for plan, count in plan_counts.items():
        embed.add_field(name=f"{plan.title()} Slots", value=f"`{count}`", inline=True)

    embed.set_footer(text=".gg/vexusfr | Slot Overview")
    await ctx.send(embed=embed)
    
@bot.command()
@commands.has_permissions(administrator=True)
async def resendinfo(ctx):
    slots = load_json(SLOTS_FILE)
    updated = 0

    for uid, slot in slots.items():
        user = bot.get_user(int(uid))
        channel = bot.get_channel(slot.get("channel_id"))

        if not user or not channel:
            continue

        # Delete old welcome message
        old_welcome_id = slot.get("welcome_msg_id")
        if old_welcome_id:
            try:
                old_msg = await channel.fetch_message(old_welcome_id)
                await old_msg.delete()
            except:
                pass

        # Send new welcome embed
        embed = slot_info_embed(slot, user, channel)
        view = CopyRecoveryKeyView(slot["recovery_key"], user.id)
        new_msg = await channel.send(embed=embed, view=view)
        slot["welcome_msg_id"] = new_msg.id
        updated += 1

    save_json(SLOTS_FILE, slots)

    await ctx.send(embed=discord.Embed(
        title=f"{CONFIG['EMOJIS']['refresh']} Slot Info Refreshed",
        description=f"Re-sent welcome/info embeds for **{updated}** active slots.",
        color=discord.Color.blurple()
    ))
    
@bot.command()
@commands.has_permissions(administrator=True)
async def clean(ctx, user: discord.Member):
    slots = load_json(SLOTS_FILE)
    uid = str(user.id)

    if uid not in slots:
        return await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} This user does not have a slot record.", color=discord.Color.red()))
    
    slot = slots[uid]
    channel_id = slot.get("channel_id")
    channel = bot.get_channel(channel_id)

    if channel:
        return await ctx.send(embed=discord.Embed(
            description=f"{CONFIG['EMOJIS']['warning']} The slot channel still exists. Use `=revoke` or `=transfer` if needed.",
            color=discord.Color.orange()
        ))

    # Channel doesn't exist, clean from file
    slots.pop(uid)
    save_json(SLOTS_FILE, slots)

    # Log in admin channel
    log_chan = bot.get_channel(ADMIN_LOG_CHANNEL)
    if log_chan:
        await log_chan.send(embed=timestamp_embed(
            "🧹 Slot Record Cleaned",
            f"Slot data for {user.mention} was cleaned because their channel no longer exists.",
            discord.Color.dark_gray()
        ))

    await ctx.send(embed=discord.Embed(
        description=f"{CONFIG['EMOJIS']['tick']} Slot data for {user.mention} has been cleaned from records.",
        color=discord.Color.green()
    ))

@bot.command()
@commands.has_permissions(administrator=True)
async def pingsreset(ctx):
    slots = load_json(SLOTS_FILE)
    updated_count = 0

    for uid, slot in slots.items():
        slot["everyone_used"] = 0
        slot["here_used"] = 0
        channel = bot.get_channel(slot["channel_id"])
        if not channel:
            continue

        try:
            def preserve(msg):
                return msg.id == slot.get("welcome_msg_id")
            await channel.purge(limit=1000, check=lambda m: not preserve(m))
        except Exception:
            pass

        try:
            embed = ping_usage_embed(0, 0, slot["plan"], slot.get("custom_limits"))
            msg = await channel.send(embed=embed)
            slot["sticky_msg_id"] = msg.id
            updated_count += 1
        except Exception:
            pass

    save_json(SLOTS_FILE, slots)

    alert_chan = bot.get_channel(PING_RESET_ALERT_CHANNEL)
    if alert_chan:
        # First ping the role so it gets notified
        await alert_chan.send(f"<@&{CONFIG['ACCESS_ROLE_ID']}>")  # Role mention outside embed

        # Then send the embed log
        await alert_chan.send(embed=timestamp_embed(
            "> **Manual Ping Reset**",
            f"-# Ping counters for all active slots have been reset manually.\n-# **{updated_count}** slot channels updated.",
            discord.Color.blurple()
        ))

    await ctx.send(embed=discord.Embed(
        description=f"{CONFIG['EMOJIS']['tick']} Manual ping reset completed for **{updated_count}** slots.",
        color=discord.Color.green()
    ))
    
@bot.command()
@commands.has_permissions(administrator=True)
async def addp(ctx, user: discord.Member, *, pings: str):
    """Add extra pings to a user. Usage: =addp @user 1x here 1x everyone"""
    slots = load_json(SLOTS_FILE)
    uid = str(user.id)
    
    if uid not in slots:
        return await ctx.send(embed=discord.Embed(
            description=f"{CONFIG['EMOJIS']['cross']} This user does not have an active slot.",
            color=discord.Color.red()
        ))
    
    slot = slots[uid]
    
    # Parse ping additions
    ping_parts = pings.lower().split()
    here_add = 0
    everyone_add = 0
    
    try:
        i = 0
        while i < len(ping_parts):
            if ping_parts[i].endswith('x'):
                amount = int(ping_parts[i][:-1])
                if i + 1 < len(ping_parts):
                    ping_type = ping_parts[i + 1]
                    if ping_type == "here":
                        here_add += amount
                    elif ping_type == "everyone":
                        everyone_add += amount
                i += 2
            else:
                i += 1
    except:
        return await ctx.send(embed=discord.Embed(
            description=f"{CONFIG['EMOJIS']['cross']} Invalid format. Use: `=addp @user 1x here 1x everyone`",
            color=discord.Color.red()
        ))
    
    # Update ping limits (not usage, but available pings)
    limits = PING_LIMITS[slot["plan"]].copy()
    limits["here"] += here_add
    limits["everyone"] += everyone_add
    
    # Store the updated limits in the slot
    if "custom_limits" not in slot:
        slot["custom_limits"] = PING_LIMITS[slot["plan"]].copy()
    slot["custom_limits"]["here"] += here_add
    slot["custom_limits"]["everyone"] += everyone_add
    
    save_json(SLOTS_FILE, slots)
    
    await ctx.send(embed=discord.Embed(
        title=f"{CONFIG['EMOJIS']['tick']} Pings Added",
        description=f"Added **{here_add}x @here** and **{everyone_add}x @everyone** to {user.mention}",
        color=discord.Color.green()
    ))

@bot.command()
@commands.has_permissions(administrator=True)
async def purge(ctx):
    try:
        deleted = await ctx.channel.purge()
        embed = discord.Embed(
            title=f"{CONFIG['EMOJIS']['purge']} Channel Purged",
            description=f"**{ctx.channel.mention}** successfully purged {CONFIG['EMOJIS']['tick']}",
            color=discord.Color.green()
        )
        embed.set_footer(text="All messages have been removed")
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=discord.Embed(
            description=f"{CONFIG['EMOJIS']['cross']} Failed to purge channel: {str(e)}",
            color=discord.Color.red()
        ))

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title=f"{CONFIG['EMOJIS']['message']} Help Menu • Slot Commands",
        description="# EliteSlots Bot — Full Command List\n\n**Note:** Commands marked with {CONFIG['EMOJIS']['shield']} require administrator permissions.",
        color=discord.Color.green()  # ← Green embed color
    )

    embed.add_field(
        name=f"{CONFIG['EMOJIS']['gem']} Slot Commands",
        value=(
            "> - **`=slotinfo [user]`** — View slot info.\n"
            "> - **`=pings`** — View remaining `@here` & `@everyone` pings.\n"
            "> - **`=timeleft`** — See when your slot expires.\n"
            "> - **`=nuke [user]`** — Clean and reset slot messages.\n"
            "> - **`=transfer <old> <new>`** {CONFIG['EMOJIS']['shield']} — Transfer a slot to another user.\n"
        ),
        inline=False
    )

    embed.add_field(
        name=f"{CONFIG['EMOJIS']['admin']} Admin Commands",
        value=(
            "> - **`=create <user> <time> <unit> <plan> <name>`** — Create a slot.\n"
            "> - **`=revoke <user> <reason>`** — Revoke a slot.\n"
            "> - **`=restore <user>`** — Restore a slot.\n"
            "> - **`=hold <user> <reason>`** — Put a slot on hold.\n"
            "> - **`=unhold <user>`** — Remove hold from a slot.\n"
            "> - **`=rename <user> <new-name>`** — Rename slot channel.\n"
            "> - **`=move <user> <plan>`** — Change slot plan.\n"
            "> - **`=clean <user>`** — Remove data for deleted slot channel.\n"
            "> - **`=resendinfo`** — Resend all welcome embeds.\n"
            "> - **`=sendrecoverypanel`** — Send recovery panel embed.\n"
            "> - **`=genslotkey`** — Generate & DM recovery keys.\n"
            "> - **`=slotstats`** — Show active/revoked slot counts.\n"
            "> - **`=pingsreset`** — Manually reset pings.\n"
            "> - **`=addp <user> <pings>`** — Add extra pings to user.\n"
            "> - **`=purge`** — Purge all messages in current channel.\n"
        ),
        inline=False
    )

    embed.set_footer(text=".gg/vexusfr | EliteSlots Help Panel")
    await ctx.send(embed=embed)  



@bot.command()
async def find(ctx, *, keyword: str):
    # Send temporary "searching..." message
    searching_msg = await ctx.send(embed=discord.Embed(
        description=f"**🔎 Searching for `{keyword}` in slots...**",
        color=discord.Color.green()
    ))

    slots = load_json(SLOTS_FILE)
    keyword = keyword.lower()
    guild = ctx.guild
    matched_channels = []
    limit_per_channel = 100

    for uid, slot in slots.items():
        channel = guild.get_channel(slot.get("channel_id"))
        if not channel:
            continue

        try:
            async for message in channel.history(limit=limit_per_channel):
                if keyword in message.content.lower():
                    matched_channels.append(channel)
                    break
        except Exception as e:
            print(f"[Find Error] Channel {channel.id}: {e}")
            continue

    embed = discord.Embed(
        title="📂 Search Results",
        description=f"**Keyword:** `{keyword}`",
        color=discord.Color.green() if matched_channels else discord.Color.red()
    )

    if matched_channels:
        embed.add_field(
            name="Mentioned In Slots:",
            value="\n".join(f"• {ch.mention}" for ch in matched_channels),
            inline=False
        )
    else:
        embed.description += "\nNo slot channels contained this keyword."

    embed.set_thumbnail(url=CONFIG["FIND_COMMAND_EMBED_THUMBNAIL"])
    embed.set_image(url=CONFIG["FIND_COMMAND_EMBED_IMAGE"])
    embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)

    # Send final result as reply
    result_msg = await ctx.reply(embed=embed, mention_author=False)

    # Delete the "searching..." message
    await searching_msg.delete()

    # Wait 90 seconds then delete result
    await asyncio.sleep(90)
    try:
        await result_msg.delete()
    except discord.NotFound:
        pass  # In case it was manually deleted already

    

@bot.command()
@commands.has_permissions(administrator=True)
async def restoreserver(ctx):
    guild = ctx.guild
    restored_active = 0
    restored_revoked = 0
    failed = 0

    try:
        slots_data = load_json(SLOTS_FILE)
        revoked_data = load_json(REVOKED_FILE)
    except Exception as e:
        await ctx.send(embed=discord.Embed(
            description=f"❌ Failed to load backup files.\n```{e}```",
            color=discord.Color.red()
        ))
        return

    # Combine all slots for processing, prioritizing active slots if there's overlap
    all_slots = {**revoked_data, **slots_data}

    admin_log_channel = bot.get_channel(ADMIN_LOG_CHANNEL)
    if not admin_log_channel:
        await ctx.send(embed=discord.Embed(description="❌ Admin log channel not found.", color=discord.Color.red()))
        return

    await ctx.send(embed=discord.Embed(
        title="🛠️ Starting Server Restore",
        description="Processing active and revoked slots... This may take a while.",
        color=discord.Color.blue()
    ))

    for uid, slot in all_slots.items():
        try:
            user = await bot.fetch_user(int(uid))
            is_revoked = uid in revoked_data

            # Determine target category
            if is_revoked:
                target_category_id = CONFIG["REVOKED_SLOT_CATEGORY_ID"]
            else:
                target_category_id = CATEGORIES.get(slot["plan"])

            category = guild.get_channel(target_category_id)
            if not category:
                print(f"[Restore Error] Category {target_category_id} not found for {uid}.")
                failed += 1
                continue

            # Channel name based on user's current name, or a placeholder if user not found
            emoji = "💜" if slot["plan"] == "elite" else "💚"
            channel_name = f"{emoji}┃{(user.name if user else uid)}".lower().replace(" ", "-")

            # Overwrites for the channel
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),  # Hide for everyone by default
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }

            # Apply specific permissions based on slot status (active/revoked)
            if is_revoked:
                # Revoked slot: hide from user, visible only to staff/admins
                if user:
                    overwrites[user] = discord.PermissionOverwrite(read_messages=False, send_messages=False)
                
                staff_role = guild.get_role(CONFIG["STAFF_ROLE_ID"])
                admin_role = discord.utils.get(guild.roles, permissions=discord.Permissions(administrator=True))
                if staff_role: overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True)
                if admin_role: overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True)

            else: # Active slot
                # User-specific permissions
                if user:
                    overwrites[user] = discord.PermissionOverwrite(
                        read_messages=True, send_messages=True, mention_everyone=True,
                        embed_links=True, attach_files=True, use_external_emojis=True
                    )

                # Default roles permissions
                hidden_role = guild.get_role(CONFIG["EVERYONE_ROLE_ID"])
                visible_role = guild.get_role(CONFIG["MEMBER_ROLE_ID"])
                if hidden_role: overwrites[hidden_role] = discord.PermissionOverwrite(read_messages=False)
                if visible_role: overwrites[visible_role] = discord.PermissionOverwrite(read_messages=True, send_messages=False)

            # Check if channel already exists and update, or create new
            channel = guild.get_channel(slot.get("channel_id"))
            if channel:
                await channel.edit(name=channel_name, category=category, overwrites=overwrites)
            else:
                channel = await guild.create_text_channel(channel_name, overwrites=overwrites, category=category)
                slot["channel_id"] = channel.id # Update slot data with new channel ID

            # Handle active slot specific behaviors
            if not is_revoked:
                # Re-send welcome embed
                if user:
                    try:
                        # Delete old welcome message if it exists
                        if slot.get("welcome_msg_id"):
                            old_welcome_msg = await channel.fetch_message(slot["welcome_msg_id"])
                            await old_welcome_msg.delete()
                    except discord.NotFound:
                        pass # Message already deleted
                    except Exception as e:
                        print(f"[Restore Error] Failed to delete old welcome message for {uid}: {e}")

                    welcome_embed = slot_info_embed(slot, user, channel)
                    welcome_msg = await channel.send(embed=welcome_embed)
                    slot["welcome_msg_id"] = welcome_msg.id

                # Assign role if member is in guild
                member = guild.get_member(user.id) if user else None
                if member:
                    role_to_assign = None
                    if slot["plan"] == "elite":
                        role_to_assign = guild.get_role(CONFIG["ELITE_ROLE_ID"])
                    elif slot["plan"] == "standard":
                        role_to_assign = guild.get_role(CONFIG["STANDARD_ROLE_ID"])

                    if role_to_assign and role_to_assign not in member.roles:
                        await member.add_roles(role_to_assign)
                    access_role = guild.get_role(CONFIG["ACCESS_ROLE_ID"])
                    if access_role and access_role not in member.roles:
                        await member.add_roles(access_role)
                # If user not in server, send DM about auto-recovery when they join
                elif user and not member:
                    # This part is for future detection when user joins
                    # For now, just ensure channel is hidden and permissions are set correctly
                    pass # The on_member_join event listener would handle this

                restored_active += 1
            else:
                restored_revoked += 1

            # Update the slot data in the correct JSON file
            if is_revoked:
                revoked_data[uid] = slot
            else:
                slots_data[uid] = slot

        except Exception as e:
            print(f"[Restore Error] Processing {uid}: {e}")
            failed += 1

    # Save updated slot files
    save_json(SLOTS_FILE, slots_data)
    save_json(REVOKED_FILE, revoked_data)

    confirmation_embed = discord.Embed(
        title="🛠️ Server Restore Completed",
        description=f"✅ Active Slots Restored: **{restored_active}**\n✅ Revoked Slots Processed: **{restored_revoked}**\n❌ Failed Entries: **{failed}**\n\nAll channels and roles have been restored based on backup data.",
        color=discord.Color.green()
    )
    await ctx.send(embed=confirmation_embed)
    await admin_log_channel.send(embed=confirmation_embed)

@bot.event
async def on_member_join(member):
    slots = load_json(SLOTS_FILE)
    uid = str(member.id)

    if uid in slots:
        slot = slots[uid]
        # Check if the user's channel exists and is hidden (indicating they were not in server during restore)
        channel = bot.get_channel(slot["channel_id"])
        if channel and not channel.permissions_for(member).read_messages:
            # User has joined, now grant permissions and role
            await channel.set_permissions(member, read_messages=True, send_messages=True, mention_everyone=True,
                                          embed_links=True, attach_files=True, use_external_emojis=True)

            # Assign role
            role_to_assign = None
            if slot["plan"] == "elite":
                role_to_assign = member.guild.get_role(CONFIG["ELITE_ROLE_ID"])
            elif slot["plan"] == "standard":
                role_to_assign = member.guild.get_role(CONFIG["STANDARD_ROLE_ID"])

            if role_to_assign and role_to_assign not in member.roles:
                await member.add_roles(role_to_assign)
            access_role = member.guild.get_role(CONFIG["ACCESS_ROLE_ID"])
            if access_role and access_role not in member.roles:
                await member.add_roles(access_role)
            # Re-send welcome embed
            try:
                if slot.get("welcome_msg_id"):
                    old_welcome_msg = await channel.fetch_message(slot["welcome_msg_id"])
                    await old_welcome_msg.delete()
            except discord.NotFound:
                pass
            except Exception as e:
                print(f"[Restore Error] Failed to delete old welcome message for {uid} on join: {e}")

            welcome_embed = slot_info_embed(slot, member, channel)
            welcome_msg = await channel.send(embed=welcome_embed)
            slot["welcome_msg_id"] = welcome_msg.id
            save_json(SLOTS_FILE, slots)

            # DM user about auto-recovery
            await dm_user(member,
                          f"{CONFIG["EMOJIS"]["tick_animated"]} Slot Automatically Recovered!",
                          f"Welcome back! Your slot in {channel.mention} has been automatically recovered and your permissions restored.",
                          discord.Color.green())

            log_chan = bot.get_channel(ADMIN_LOG_CHANNEL)
            if log_chan:
                await log_chan.send(embed=timestamp_embed(
                    f"{CONFIG["EMOJIS"]["tick_animated"]} Slot Auto-Recovered",
                    f"Slot for {member.mention} auto-recovered upon joining the server.",
                    discord.Color.green()
                ))

# --- Error handling for commands ---
@create.error
@revoke.error
@restore.error
@hold.error
@unhold.error
async def admin_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} You don't have permission to use this command.", color=discord.Color.red()))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} Invalid argument. Please check your input.", color=discord.Color.red()))
    else:
        await ctx.send(embed=discord.Embed(description=f"{CONFIG['EMOJIS']['cancel/cross']} An error occurred: {error}", color=discord.Color.red()))

        
# --- Run the bot ---
bot.run(CONFIG["YOUR_BOT_TOKEN"])


