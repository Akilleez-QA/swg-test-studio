#include "LoginRecoveryAdmission.h"
#include <cassert>
#include <cstdio>

typedef LoginRecoveryAdmission Admission;
typedef std::vector<Admission::Candidate> Candidates;
static Admission::Endpoint const oldCopy("space_ord_mantell_2", "public");
static Admission::Endpoint const liveCopy("space_ord_mantell_3", "public");
static Admission::Endpoint const safeExit("kashyyyk_main", "slaver_exit");

static Admission::Request request(std::string const &character, unsigned long deadline = 200)
{
	Admission::Request r;
	r.character = character;
	r.attempt = "attempt-1";
	r.original = oldCopy;
	r.deadline = deadline;
	return r;
}

static Candidates equivalents()
{
	Candidates c;
	c.push_back(Admission::Candidate(oldCopy, 1, Admission::Resume, true));
	c.push_back(Admission::Candidate(liveCopy, 1, Admission::PublicEquivalent, true));
	c.push_back(Admission::Candidate(safeExit, 1, Admission::SafeExit, true));
	return c;
}

static void ready(Admission &a, Admission::Endpoint const &e, unsigned int capacity = 1)
{ assert(a.observe(e, 1, 1, 100, 60, capacity, 0, true, true)); }

static void selection()
{
	Admission a(10);
	ready(a, liveCopy);
	ready(a, safeExit);
	Admission::Reservation first, other;
	Admission::Request r = request("first");
	assert(a.reserve(r, equivalents(), 100, 20, first) == Admission::Granted);
	assert(first.endpoint == liveCopy); // No contiguous suffix assumption; old copy absent.
	assert(a.reserve(request("second"), equivalents(), 100, 20, other) == Admission::Granted);
	assert(other.endpoint == safeExit); // Last slot in live copy is already reserved.
	assert(a.reserve(request("third"), equivalents(), 100, 20, other) == Admission::NoReadyDestination);
	assert(other.id == 0); // Never leak a previous destination on failure.
	assert(a.reserve(r, equivalents(), 101, 20, other) == Admission::Granted);
	assert(other.id == first.id && other.expires == first.expires && a.pending() == 2);
	r.attempt = "attempt-2";
	assert(a.reserve(r, equivalents(), 101, 20, other) == Admission::AttemptPending);
	assert(!a.cancel(first.id, "another-player", "attempt-1"));
	assert(a.cancel(first.id, "first", "attempt-1"));
	assert(a.reserve(request("first"), equivalents(), 101, 20, other) == Admission::AttemptFinished);
	assert(a.reserve(r, equivalents(), 101, 20, other) == Admission::Granted);
	assert(other.id != first.id);
}

static void privateAndPlacement()
{
	Admission a(10);
	ready(a, oldCopy);
	ready(a, liveCopy);
	ready(a, safeExit);
	Admission::Request r = request("private");
	r.privateSession = true;
	Admission::Reservation result;
	assert(a.reserve(r, equivalents(), 100, 20, result) == Admission::Granted);
	assert(result.endpoint == safeExit); // Expired private session never gets another party's instance.
	assert(a.cancel(result.id, r.character, r.attempt));
	r.attempt = "attempt-2";
	r.originalSessionValid = true;
	assert(a.reserve(r, equivalents(), 100, 20, result) == Admission::Granted);
	assert(result.endpoint == oldCopy);
	assert(a.cancel(result.id, r.character, r.attempt));
	r.attempt = "attempt-3";
	Candidates unverified;
	unverified.push_back(Admission::Candidate(liveCopy, 1, Admission::PublicEquivalent, false));
	r.privateSession = false;
	assert(a.reserve(r, unverified, 100, 20, result) == Admission::NoReadyDestination);
	assert(result.id == 0);
}

static void stateAndGeneration()
{
	Admission a(10);
	Admission::Reservation result;
	Admission::Request r = request("generation");
	assert(a.observe(liveCopy, 1, 1, 100, 60, 1, 0, false, true));
	assert(a.reserve(r, equivalents(), 100, 20, result) == Admission::NoReadyDestination);
	assert(a.observe(liveCopy, 1, 2, 100, 60, 1, 0, true, false));
	assert(a.reserve(r, equivalents(), 100, 20, result) == Admission::NoReadyDestination);
	assert(a.observe(liveCopy, 1, 3, 100, 60, 1, 0, true, true));
	assert(a.reserve(r, equivalents(), 100, 20, result) == Admission::Granted);
	assert(!a.observe(liveCopy, 1, 2, 100, 60, 1, 0, true, true));
	assert(a.observe(liveCopy, 2, 1, 101, 60, 1, 0, true, true));
	assert(!a.beginCommit(result.id, r.character, r.attempt, 101));
	assert(!a.observe(liveCopy, 1, 99, 101, 60, 1, 0, true, true));
	assert(a.cancel(result.id, r.character, r.attempt));
	r.attempt = "attempt-2";
	assert(a.reserve(r, equivalents(), 101, 20, result) == Admission::NoReadyDestination);
	Candidates fresh;
	fresh.push_back(Admission::Candidate(liveCopy, 2, Admission::PublicEquivalent, true));
	assert(a.reserve(r, fresh, 101, 20, result) == Admission::Granted);
	assert(a.observe(liveCopy, 2, 2, 102, 60, 1, 1, true, true));
	assert(!a.beginCommit(result.id, r.character, r.attempt, 102)); // New occupancy exhausted headroom.
}

static void commitAccounting()
{
	Admission a(10);
	ready(a, liveCopy);
	Admission::Request r = request("committing");
	Admission::Reservation result;
	assert(a.reserve(r, equivalents(), 100, 5, result) == Admission::Granted);
	assert(!a.beginCommit(result.id, "wrong-player", r.attempt, 101));
	assert(a.beginCommit(result.id, r.character, r.attempt, 101));
	assert(!a.beginCommit(result.id, r.character, r.attempt, 101));
	assert(!a.cancel(result.id, r.character, r.attempt));
	assert(!a.settle(result.id, r.character, r.attempt, 1, 1, 101));
	Admission::Reservation other;
	assert(a.reserve(r, equivalents(), 110, 5, other) == Admission::AttemptPending);
	assert(a.reserve(request("competitor"), equivalents(), 110, 5, other) == Admission::NoReadyDestination);
	// Unknown placement result retains its slot even after the reservation deadline.
	assert(a.pending() == 1);
	assert(a.observe(liveCopy, 1, 2, 110, 60, 1, 1, true, true));
	assert(!a.settle(result.id, r.character, "wrong-attempt", 1, 2, 110));
	assert(!a.settle(result.id, r.character, r.attempt, 2, 2, 110));
	assert(a.settle(result.id, r.character, r.attempt, 1, 2, 110));
	assert(!a.settle(result.id, r.character, r.attempt, 1, 2, 110));
	assert(a.pending() == 0);
	assert(a.reserve(r, equivalents(), 110, 5, other) == Admission::AttemptFinished);
	assert(a.reserve(request("competitor"), equivalents(), 110, 5, other) == Admission::NoReadyDestination);
}

static void boundsAndFreshness()
{
	Admission a(1);
	ready(a, liveCopy, 2);
	Admission::Request r = request("expiry", 107);
	Admission::Reservation result, other;
	assert(a.reserve(r, equivalents(), 100, 20, result) == Admission::Granted);
	assert(result.expires == 107);
	assert(a.reserve(request("limit"), equivalents(), 100, 20, other) == Admission::LimitReached);
	assert(!a.beginCommit(result.id, r.character, r.attempt, 107));
	assert(a.reserve(request("replacement"), equivalents(), 107, 100, other) == Admission::Granted);
	assert(other.expires == 160); // May not outlive the last ready observation.
	assert(!a.beginCommit(other.id, "replacement", "attempt-1", 160));
	assert(a.reserve(request("stale"), equivalents(), 160, 10, result) == Admission::NoReadyDestination);
	assert(a.reserve(request("backwards"), equivalents(), 159, 10, result) == Admission::InvalidRequest);
	assert(!a.observe(liveCopy, 1, 2, 160, 10, 1, 2, true, true));
	assert(!a.observe(liveCopy, 1, 2, 160, std::numeric_limits<Admission::Tick>::max(), 1, 0, true, true));
	assert(a.reserve(request("timeout", 160), equivalents(), 160, 10, result) == Admission::InvalidRequest);
	assert(a.reserve(request(""), equivalents(), 160, 10, result) == Admission::InvalidRequest);
}

static void sharedHostAndDrain()
{
	Admission a(10);
	Admission::Endpoint retired("kashyyyk_rryatt_trail", "set-2");
	Admission::Endpoint active("kashyyyk_rryatt_trail", "set-5");
	ready(a, retired);
	ready(a, active);
	assert(a.observe(retired, 1, 2, 100, 60, 1, 0, false, true));
	Admission::Request r = request("rryatt");
	r.original = retired;
	r.originalSessionValid = true;
	Candidates c;
	c.push_back(Admission::Candidate(retired, 1, Admission::Resume, true));
	c.push_back(Admission::Candidate(active, 1, Admission::PublicEquivalent, true));
	Admission::Reservation result;
	assert(a.reserve(r, c, 100, 20, result) == Admission::Granted);
	assert(result.endpoint == active);
	assert(a.observe(active, 1, 2, 101, 60, 1, 0, false, true));
	assert(!a.beginCommit(result.id, r.character, r.attempt, 101));
	assert(a.cancel(result.id, r.character, r.attempt));
	assert(a.reserve(r, c, 102, 20, result) == Admission::AttemptFinished);
}

int main()
{
	assert(sizeof(void *) == 8);
	selection(); privateAndPlacement(); stateAndGeneration(); commitAccounting(); boundsAndFreshness();
	sharedHostAndDrain();
	std::printf("ELF64 login recovery admission passed: selection, private sessions, slots, retries, generations, commit reconciliation, deadlines.\n");
}
