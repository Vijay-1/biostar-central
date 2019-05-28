import logging
from mistune import markdown
from allauth.socialaccount.models import SocialApp
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout, login
from django.shortcuts import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.views import (PasswordResetView, PasswordResetDoneView,
                                       PasswordResetConfirmView, PasswordResetCompleteView,
                                       )
from django.core import signing
from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.utils.encoding import force_text
from django.utils.http import urlsafe_base64_decode
from django.utils.safestring import mark_safe
from ratelimit.decorators import ratelimit


from . import forms
from .auth import check_user, send_verification_email
from .const import *
from .models import User, Profile, Message
from .tokens import account_verification_token
from .util import now, get_uuid


logger = logging.getLogger('engine')


def edit_profile(request):
    if request.user.is_anonymous:
        messages.error(request, "Must be logged in to edit profile")
        return redirect("/")

    user = request.user
    initial = dict(username=user.username, email=user.email, name=user.profile.name,location=user.profile.location,
                   website=user.profile.website, twitter=user.profile.twitter,scholar=user.profile.scholar,
                   text=user.profile.text, my_tags=user.profile.my_tags, digest_prefs=user.profile.digest_prefs,
                   message_prefs=user.profile.message_prefs, email_verified=user.profile.email_verified)

    form = forms.EditProfile(user=user, initial=initial)

    if request.method == "POST":
        form = forms.EditProfile(data=request.POST, user=user, initial=initial, files=request.FILES)
        if form.is_valid():
            # Update the email and username of User object.
            email = form.cleaned_data['email']
            username = form.cleaned_data["username"]
            User.objects.filter(pk=user.pk).update(username=username, email=email)

            # Change verification if email has been edited.
            email_verified = False if user.email != initial["email"] else user.profile.email_verified
            # Update user information in Profile object.
            Profile.objects.filter(user=user).update(name=form.cleaned_data['name'],
                                                     location=form.cleaned_data['location'],
                                                     website=form.cleaned_data['website'],
                                                     twitter=form.cleaned_data['twitter'],
                                                     scholar=form.cleaned_data['scholar'],
                                                     text=form.cleaned_data["text"],
                                                     my_tags=form.cleaned_data["my_tags"],
                                                     digest_prefs=form.cleaned_data["digest_prefs"],
                                                     message_prefs=form.cleaned_data["message_prefs"],
                                                     html=markdown(form.cleaned_data["text"]),
                                                     email_verified=email_verified)

            return redirect(reverse("user_profile", kwargs=dict(uid=user.profile.uid)))

    context = dict(user=user, form=form)
    return render(request, 'accounts/edit_profile.html', context=context)


def listing(request):

    users = User.objects.all()
    context = dict(users=users)
    return render(request, "accounts/listing.html", context=context)

# def ban_user(user):
#
#     # Delete the posts, votes, awards, messages, and subs
#     Post.objects.filter(author=user).delete()
#     Message.objects.filter(sender=user).delete()
#     Subscription.objects.filter(user=user).delete()
#     Award.objects.filter(user=user).delete()
#     Vote.objects.filter(author=user).delete()
#
#     User.objects.filter(pk=user.id).update(email=f"banned-{user.id}@nomail.com", username=f"banned-{user.id}")
#     Profile.objects.filter(user=user).update(name="banned", text="", html="")
#     edited_posts = Post.objects.filter(lastedit_user=user)
#
#     def gen():
#         for post in edited_posts:
#             post.lastedit_user = post.author
#             yield post
#
#     Post.objects.bulk_update(objs=gen(), fields=["lastedit_user"], batch_size=10)
#     #User.objects.filter(pk=user.id).first().delete()
#     return


@login_required
def user_moderate(request, uid):
    source = request.user
    target = User.objects.filter(profile__uid=uid).first()

    if request.method == "POST":

        form = forms.UserModerate(source=source, data=request.POST, target=target, request=request)
        if form.is_valid():
            state = form.cleaned_data.get("action", "")
            Profile.objects.filter(user=target).update(state=state)
            if Profile.BANNED == state:
                # Delete posts of banned users
                Profile.objects.filter(user=target).update(state=state)
                #ban_user(user=target)
            messages.success(request, "User moderation complete.")
        else:
            messages.error(request, "Invalid user moderation.")
        return redirect(reverse("user_profile", kwargs=dict(uid=uid)))

    else:
        form = forms.UserModerate(source=source, target=target, request=request)

    context = dict(form=form, target=target)
    return render(request, "accounts/user_moderate.html", context)


@login_required
def message_list(request):
    """
    Show messages belonging to user.
    """
    user = request.user
    page = request.GET.get("page", 1)
    msgs = Message.objects.filter(recipient=user)
    msgs = msgs.select_related("sender", "sender__profile")
    msgs = msgs.order_by("-sent_date")
    # Update the unread flag
    Message.objects.filter(id__in=msgs).update(unread=False)

    # Get the pagination info
    paginator = Paginator(msgs, settings.MESSAGES_PER_PAGE)
    msgs = paginator.get_page(page)

    context = dict(tab="messages", all_messages=msgs)
    Profile.objects.filter(user=user).update(new_messages=0)

    return render(request, "messages/message_list.html", context)


def user_profile(request, uid):
    profile = Profile.objects.filter(uid=uid).first()

    if not profile:
        messages.error(request, "User does not exist")
        return redirect("/")

    # Get the active tab, defaults to project
    active_tab = request.GET.get("active", "posts")
    # User viewing profile is a moderator
    can_moderate = request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)
    context = dict(target=profile.user, active=active_tab, debugging=settings.DEBUG,
                   const_post=POSTS, const_project=PROJECT, can_moderate=can_moderate, tab="profile")

    return render(request, "accounts/user_profile.html", context)


def toggle_notify(request):
    if request.user.is_anonymous:
        messages.error(request, "Must be logged in to edit profile")
        return redirect("/")

    user = request.user
    user.profile.notify = not user.profile.notify
    user.profile.save()

    msg = "Emails notifications disabled."
    if user.profile.notify:
        msg = "Emails notifications enabled."

    messages.success(request, msg)
    return redirect(reverse('user_profile', kwargs=dict(uid=user.profile.uid)))


@ratelimit(key='ip', rate='10/m', block=True, method=ratelimit.UNSAFE)
def user_signup(request):
    #if not settings.ALLOW_SIGNUP:
    #    messages.error(request, "Signups are not yet enabled on this site.")
    #    return redirect(reverse("login"))

    if request.method == 'POST':

        form = forms.SignUpWithCaptcha(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            Profile.objects.filter(user=user).update(last_login=now())
            messages.success(request, "Login successful!")
            msg = mark_safe("Signup successful!")
            messages.info(request, msg)

            return redirect("/")
    else:
        form = forms.SignUpWithCaptcha()

    context = dict(form=form, captcha_site_key=settings.RECAPTCHA_PUBLIC_KEY,
                   social_login=SocialApp.objects.all())
    return render(request, 'accounts/signup.html', context=context)


@user_passes_test(lambda u: u.is_superuser)
def debug_user(request):
    """
    Allows superusers to log in as a regular user to troubleshoot problems.
    """

    if not settings.DEBUG:
        messages.error(request, "Can only use when in debug mode.")
        redirect("/")

    target = request.GET.get("uid", "")
    profile = Profile.objects.filter(uid=target).first()

    if not profile:
        messages.error(request, "User does not exists.")
        return redirect("/")

    user = profile.user
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    messages.success(request, "Login successful!")

    logger.info(f"""uid={request.user.profile.uid} impersonated 
                    uid={profile.uid}.""")

    return redirect("/")


def user_logout(request):
    if request.method == "POST":

        form = forms.LogoutForm(request.POST)

        if form.is_valid():
            logout(request)
            messages.info(request, "You have been logged out")
            return redirect("/")

    form = forms.LogoutForm()

    context = dict(form=form)

    return render(request, "accounts/logout.html", context=context)


def user_login(request):
    form = forms.LoginForm()

    if request.method == "POST":
        form = forms.LoginForm(data=request.POST)

        if form.is_valid():

            email = form.cleaned_data['email']
            password = form.cleaned_data['password']

            user = User.objects.filter(email__iexact=email).order_by('-id').first()
            message, valid_user = check_user(email=email, password=password)

            if valid_user:
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                Profile.objects.filter(user=user).update(last_login=now())
                messages.success(request, "Login successful!")
                redir = settings.LOGIN_REDIRECT_URL or "/"
                return redirect(redir)
            else:
                messages.error(request, mark_safe(message))

        messages.error(request, mark_safe(form.errors))

    context = dict(form=form, social_login=SocialApp.objects.all())
    return render(request, "accounts/login.html", context=context)


@login_required
def send_email_verify(request):
    "Send one-time valid link to validate email"

    # Sends verification email with a token
    user = request.user

    send_verification_email(user=user)

    messages.success(request, "Verification sent, check your email.")

    return redirect(reverse("user_profile", kwargs=dict(uid=user.profile.uid)))


def email_verify_account(request, uidb64, token):
    "Verify one time link sent to a users email"

    uid = force_text(urlsafe_base64_decode(uidb64))
    user = User.objects.filter(pk=uid).first()

    if user and account_verification_token.check_token(user, token):
        Profile.objects.filter(user=user).update(email_verified=True)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Email verified!")
        return redirect(reverse('user_profile', kwargs=dict(uid=user.profile.uid)))

    messages.error(request, "Link is expired.")
    return redirect("/")


def external_login(request):
    """Login or signup a user."""
    payload = request.GET.get("payload", "")

    try:
        signer = signing.Signer(settings.LOGIN_PRIVATE_KEY)
        user_email = signer.unsign(payload)
        user = User.objects.filter(email=user_email).first()

        if not user:
            name = user_email.split("@")[0]
            user = User.objects.create(email=user_email, first_name=name,
                                       password=str(get_uuid(16)))
            user.username = name.split()[0] + str(get_uuid(8))
            user.save()
            msg = f"Signed up, <a href={reverse('password_reset')}><b> Please reset your password.</b></a>"
            messages.success(request, mark_safe(msg))

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Logged in!")
        return redirect("/")

    except Exception as exc:
        logger.error(f"Error:{exc}")
        messages.error(request, "Error unsigning.")

    return redirect("/")


def password_reset(request):
    context = dict()

    return PasswordResetView.as_view(extra_context=context,
                                     template_name="accounts/password_reset_form.html",
                                     subject_template_name="accounts/password_reset_subject.txt",
                                     email_template_name="accounts/password_reset_email.html"
                                     )(request=request)


def password_reset_done(request):
    context = dict()

    return PasswordResetDoneView.as_view(extra_context=context,
                                         template_name="accounts/password_reset_done.html")(request=request)


def pass_reset_confirm(request, uidb64, token):
    context = dict()

    return PasswordResetConfirmView.as_view(extra_context=context,
                                            template_name="accounts/password_reset_confirm.html")(request=request,
                                                                                                  uidb64=uidb64,
                                                                                                  token=token)


def password_reset_complete(request):
    context = dict()

    return PasswordResetCompleteView.as_view(extra_context=context,
                                             template_name="accounts/password_reset_complete.html")(request=request)
