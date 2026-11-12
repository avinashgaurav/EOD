# Homebrew cask for EOD, served from this repository (no separate tap repo):
#   brew tap avinashgaurav/eod https://github.com/avinashgaurav/EOD
#   brew install --cask eod
# EOD is not signed with a paid Apple Developer ID. If macOS blocks the first
# open, use System Settings > Privacy & Security > Open Anyway, once.
cask "eod" do
  version :latest
  sha256 :no_check

  url "https://github.com/avinashgaurav/EOD/releases/latest/download/EOD.zip"
  name "EOD"
  desc "Your standup, already written: a menu-bar receipt of your work day"
  homepage "https://eodreceipt.vercel.app"

  depends_on macos: ">= :ventura"

  app "EOD.app"

  zap trash: "~/Library/Application Support/EOD"
end
